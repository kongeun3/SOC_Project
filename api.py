"""
SOC 졸업설계 — 도로 포장 열응력 진단 시스템 v2.0
─────────────────────────────────────────────────────
주요 기능:
  • V1/V2/V3 검증 시나리오 선택 (수학적 무결성 / TSRST 벤치마크 / 극한 위험)
  • 격자 해상도 옵션 (40×40 / 60×60 / 80×80)
  • 물성치 직접 조정 (E, ν, α, S_t)
  • CSV 절대온도 입력 자동 감지 (FLIR Tools)
  • 불확실성 정량화 (FLIR ±3°C → 응력 변동)
  • 응력 이력 곡선 데이터 (1h~6h 냉각)
  • 위험 위치 오버레이 이미지
  • 전문가급 LLM 진단 (시스템 프롬프트 강화)
"""

import os
import json
from pathlib import Path
from typing import Literal
from config import (
    WEIGHTS_DIR,
    JOBS_DIR,
    JOB_QUEUE_CAPACITY,
    SESSION_TTL_SECONDS,
    MAX_SESSIONS,
    MAX_JOBS_PER_SESSION,
    MAX_UPLOADS_PER_SESSION,
    MAX_PENDING_PER_SESSION,
    MAX_UPLOAD_MB,
    OLLAMA_BASE,
    OLLAMA_MODEL,
)
from core.job_manager import JobManager, JobError
import requests
import traceback
import numpy as np
from datetime import date, datetime
from fastapi import FastAPI, UploadFile, File, Header, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image as PILImage, ExifTags

# ── [1] 경로 자동 설정 ──────────────────────────────────────
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rc("font", family="Malgun Gothic")
plt.rcParams["axes.unicode_minus"] = False

try:
    from core.thermal_stress_fem_system import (
        get_material_properties,
        generate_cst_mesh,
        assemble_and_solve,
        compute_risk_map,
        verification_suite,
        visualize_results,
        effective_relaxation_modulus,
    )
    from core.thermal_artifact_correction import ThermalPreprocessor
    from core.morphology import (
        apply_morphological_dilation,
    )
except ImportError as e:
    print(f"⚠️ 모듈 임포트 실패: {e}")

try:
    from core.thermal_image_loader import csv_to_temperature

    CSV_LOADER_OK = True
except Exception as e:
    print(f"⚠️ thermal_image_loader 미사용: {e}")
    CSV_LOADER_OK = False

# ── [3] 시나리오 정의 (thermal_stress_fem_system와 동일) ────
SCENARIOS = {
    "default": {
        "name": "운영 모드",
        "desc": "현장 분석용 기본 파라미터",
        "bc": "roller_symmetric",
        "wk": 13.5e6,
        "tr": 7200.0,
    },
    "v1": {
        "name": "V1 — 수학적 무결성 검증",
        "desc": "fully_fixed BC → 2D 이론해 σ=E·α·ΔT/(1-ν) 일치 (오차 ~0%)",
        "bc": "fully_fixed",
        "wk": 13.5e6,
        "tr": 7200.0,
    },
    "v2": {
        "name": "V2 — TSRST 벤치마크",
        "desc": "t_relax=6h (시간당 10°C 냉각) → 문헌 파괴응력 3.5MPa 일치",
        "bc": "roller_symmetric",
        "wk": 13.5e6,
        "tr": 21600.0,
    },
    "v3": {
        "name": "V3 — 극한 위험 탐지",
        "desc": "winkler×10 (강한 지반 마찰) → Critical 영역 가시화",
        "bc": "roller_symmetric",
        "wk": 135e6,
        "tr": 7200.0,
    },
}

# ── [4] FastAPI 초기화 ──────────────────────────────────────
app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

job_manager = JobManager(
    JOBS_DIR,
    queue_capacity=JOB_QUEUE_CAPACITY,
    session_ttl=SESSION_TTL_SECONDS,
    max_sessions=MAX_SESSIONS,
    max_jobs_per_session=MAX_JOBS_PER_SESSION,
    max_uploads_per_session=MAX_UPLOADS_PER_SESSION,
    max_pending_per_session=MAX_PENDING_PER_SESSION,
)
tuner = None
sam_transform = None
DEVICE = None
sam2_available = False


# ── [5] SAM2 로드 ───────────────────────────────────────────
def load_sam2_model():
    global tuner, sam_transform, DEVICE, sam2_available
    try:
        import torch
        from core.segmentation import SAM2PromptTuner
        from sam2.utils.transforms import SAM2Transforms

        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        weights_path = str(WEIGHTS_DIR)
        tuner = SAM2PromptTuner(
            os.path.join(weights_path, "sam2.1_hiera_b+.yaml"),
            os.path.join(weights_path, "checkpoint_8.pt"),
            num_tokens=10,
        ).to(DEVICE)
        prompt_data = torch.load(
            os.path.join(weights_path, "prompt_tuned_ep20.pt"),
            map_location=DEVICE,
            weights_only=False,
        )
        tuner.learnable_sparse_embeddings.data = prompt_data[
            "learnable_sparse_embeddings"
        ]
        tuner.eval()
        sam_transform = SAM2Transforms(resolution=1024, mask_threshold=0.0)
        sam2_available = True
        print("✅ SAM2 로드 성공")
    except Exception as e:
        print(f"⚠️ SAM2 로드 실패: {e}")
        sam2_available = False


load_sam2_model()

# ── [6] Ollama 헬퍼 ─────────────────────────────────────────


def check_ollama_connection(require_model: bool = False) -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        if r.status_code != 200:
            return False
        if require_model:
            return any(
                model.get("name") == OLLAMA_MODEL
                for model in r.json().get("models", [])
            )
        return True
    except Exception:
        return False


def is_valid_response(text: str) -> bool:
    """LLM 응답이 정상적인지 검증."""
    if not text:
        return False
    cleaned = text.strip().lower()
    # 너무 짧거나 단어 하나만 있으면 비정상
    if len(cleaned) < 30:
        return False
    # 흔한 잘못된 응답 패턴
    bad_patterns = [
        "fem",
        "'fem'",
        '"fem"',
        "finite element",
        "sam2",
        "llm",
        "...",
        "n/a",
    ]
    if cleaned in bad_patterns:
        return False
    # 한국어가 거의 없으면 비정상 (한글 음절 영역)
    korean_chars = sum(1 for c in text if "\uAC00" <= c <= "\uD7A3")
    if korean_chars < 10:
        return False
    return True


def call_ollama(
    prompt: str,
    timeout: int = 180,
    num_predict: int = 600,
    system: str | None = None,
    max_retries: int = 2,
) -> str:
    """Ollama API 호출 + 응답 검증 + 자동 재시도."""
    print(
        f"[Ollama] {OLLAMA_MODEL} 호출 - timeout={timeout}s, num_predict={num_predict}"
    )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_response = ""
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": num_predict,
                        "temperature": 0.5 + attempt * 0.1,  # 재시도마다 다양성↑
                        "top_p": 0.9,
                        "repeat_penalty": 1.15,
                    },
                },
                timeout=timeout,
            )
            r.raise_for_status()
            result = r.json()["message"]["content"]
            last_response = result
            print(f"[Ollama] 응답 #{attempt+1} ({len(result)}자): {result[:60]}...")

            if is_valid_response(result):
                return result
            else:
                print(f"[Ollama] ⚠️ 응답 비정상 — 재시도 {attempt+1}/{max_retries}")
                # 재시도 시 system 메시지를 더 강하게
                if attempt < max_retries:
                    messages = [
                        (
                            {
                                "role": "system",
                                "content": system
                                + "\n\n※중요: 반드시 한국어로 5문장 이상 답하세요. 영어 단어 한 개로 답하면 안 됩니다.",
                            }
                            if system
                            else {
                                "role": "system",
                                "content": "한국어로 5문장 이상 답하세요. 단어 하나로 답하지 마세요.",
                            }
                        ),
                        {"role": "user", "content": prompt},
                    ]
        except requests.exceptions.Timeout:
            return f"❌ LLM 응답 시간 초과 ({timeout}초)"
        except requests.exceptions.ConnectionError:
            return "❌ Ollama 서버(127.0.0.1:11434) 연결 실패. 'ollama serve' 실행 확인"
        except Exception as e:
            print(f"[Ollama] 예외: {e}")
            return f"❌ LLM 오류: {type(e).__name__}: {e}"

    # 모든 재시도 실패 → 폴백 (데이터 기반)
    print("[Ollama] 모든 재시도 실패 → 폴백 사용")
    return f"⚠️ LLM 응답 비정상 (마지막 응답: '{last_response[:30]}'). 분석 결과는 위 메트릭 카드를 참조하세요."


# ── [7] 촬영일 추출 ─────────────────────────────────────────
def get_capture_date(image_path: str, override: str | None = None) -> tuple[str, str]:
    if override:
        try:
            datetime.strptime(override, "%Y-%m-%d")
            return override, "manual"
        except ValueError:
            pass
    try:
        img = PILImage.open(image_path)
        exif = img._getexif() or {}
        for tag, val in exif.items():
            if ExifTags.TAGS.get(tag) == "DateTimeOriginal" and isinstance(val, str):
                return val.split(" ")[0].replace(":", "-"), "exif"
    except Exception:
        pass
    return date.today().isoformat(), "today"


# ── [8] 시각화 ──────────────────────────────────────────────
def save_pipeline_image(
    image_np, expanded_mask, thermal_matrix, risk_map, nodes, elements, output_dir
):
    fig, axes = plt.subplots(1, 4, figsize=(24, 6))
    axes[0].imshow(image_np)
    axes[0].axis("off")
    axes[1].imshow(expanded_mask, cmap="gray")
    axes[1].axis("off")
    gray_bg = np.full(
        (thermal_matrix.shape[0], thermal_matrix.shape[1], 3), 30, dtype=np.uint8
    )
    valid_mask = np.isfinite(thermal_matrix)
    if np.any(valid_mask):
        norm = plt.Normalize(
            vmin=np.nanmin(thermal_matrix), vmax=np.nanmax(thermal_matrix)
        )
        colored = (
            plt.get_cmap("jet")(norm(thermal_matrix[valid_mask]))[:, :3] * 255
        ).astype(np.uint8)
        gray_bg[valid_mask] = colored
    axes[2].imshow(gray_bg)
    axes[2].axis("off")
    draw_risk_overlay(axes[3], image_np, risk_map, nodes, elements)
    plt.tight_layout()
    plt.savefig(
        os.path.join(output_dir, "pipeline_result.png"),
        dpi=80,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def draw_risk_overlay(ax, image_np, risk_map, nodes, elements):
    """주어진 축에 원본 이미지와 FEM 위험 위치를 겹쳐 그린다."""
    h, w = image_np.shape[:2]
    ax.imshow(image_np)

    # 메시 좌표 → 이미지 픽셀 좌표 변환
    mesh_min = nodes.min(axis=0)
    mesh_span = np.maximum(nodes.max(axis=0) - mesh_min, 1e-12)
    centers = nodes[elements].mean(axis=1)
    pixel_x = (centers[:, 0] - mesh_min[0]) / mesh_span[0] * (w - 1)
    pixel_y = (1.0 - (centers[:, 1] - mesh_min[1]) / mesh_span[1]) * (h - 1)

    # 응력비 0.5 이상만 표시 (시각적 노이즈 줄이기)
    for selected, color, alpha, size in (
        ((risk_map >= 0.5) & (risk_map < 0.7), "yellow", 0.35, 30),
        ((risk_map >= 0.7) & (risk_map < 1.0), "orange", 0.6, 50),
        (risk_map >= 1.0, "red", 0.85, 80),
    ):
        ax.scatter(
            pixel_x[selected],
            pixel_y[selected],
            c=color,
            s=size,
            alpha=alpha,
            edgecolors="white",
            linewidth=0.5,
        )

    # 최대 응력 위치 강조
    worst_idx = int(np.argmax(risk_map))
    wx, wy = pixel_x[worst_idx], pixel_y[worst_idx]
    ax.scatter(
        wx,
        wy,
        c="white",
        s=300,
        marker="X",
        edgecolors="black",
        linewidth=2.5,
        zorder=10,
    )
    ax.text(
        0.02,
        0.02,
        f"최대 응력비 {risk_map.max():.3f}",
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        color="white",
        bbox=dict(boxstyle="round,pad=0.3", fc="red", alpha=0.9),
    )
    ax.set_xlim(-0.5, w - 0.5)
    ax.set_ylim(h - 0.5, -0.5)
    ax.axis("off")


def save_risk_overlay(image_np, risk_map, nodes, elements, n_rows, n_cols, output_dir):
    """원본 이미지 위에 위험 위치를 시각적으로 오버레이."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    draw_risk_overlay(ax, image_np, risk_map, nodes, elements)
    plt.tight_layout()
    plt.savefig(
        os.path.join(output_dir, "risk_overlay.png"),
        dpi=80,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def save_distribution_chart(risk_map, S_t, output_dir):
    """응력비 분포 히스토그램."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    bins = np.linspace(0, max(1.5, risk_map.max() * 1.05), 40)
    counts, edges, patches = ax.hist(
        risk_map, bins=bins, edgecolor="white", linewidth=0.8
    )

    # 색상: 응력비 따라 그라데이션
    for i, p in enumerate(patches):
        center = (edges[i] + edges[i + 1]) / 2
        if center >= 1.0:
            p.set_facecolor("#D32F2F")  # 빨강
        elif center >= 0.7:
            p.set_facecolor("#F57C00")  # 주황
        else:
            p.set_facecolor("#388E3C")  # 초록

    ax.axvline(
        0.7, color="orange", linestyle="--", linewidth=2, label="경고 임계 (SR=0.7)"
    )
    ax.axvline(
        1.0, color="red", linestyle="--", linewidth=2, label="파괴 임계 (SR=1.0)"
    )
    ax.set_xlabel("응력비 (Stress Ratio = |σ| / S_t)", fontsize=12)
    ax.set_ylabel("요소 개수", fontsize=12)
    ax.set_title(
        f"응력비 분포 — 인장강도 S_t = {S_t} MPa", fontsize=13, fontweight="bold"
    )
    ax.legend(loc="upper right", fontsize=11)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(
        os.path.join(output_dir, "distribution.png"),
        dpi=80,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def save_donut_chart(critical, warning, safe, total, output_dir):
    """Critical/Warning/Safe 도넛 차트."""
    fig, ax = plt.subplots(1, 1, figsize=(5, 5), subplot_kw=dict(aspect="equal"))
    sizes = [critical, warning, safe]
    colors = ["#D32F2F", "#F57C00", "#388E3C"]
    # 0인 항목은 제거 (시각적 노이즈)
    filtered = [(s, c) for s, c in zip(sizes, colors) if s > 0]
    if not filtered:
        plt.close(fig)
        return
    sizes, colors = zip(*filtered)

    ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        wedgeprops=dict(width=0.4, edgecolor="white", linewidth=2),
    )
    # 중앙 텍스트
    ax.text(
        0,
        0.05,
        f"{total}",
        ha="center",
        va="center",
        fontsize=28,
        fontweight="bold",
        color="#0D1B4C",
    )
    ax.text(0, -0.18, "총 요소", ha="center", va="center", fontsize=11, color="#607D8B")
    plt.tight_layout()
    plt.savefig(
        os.path.join(output_dir, "donut.png"),
        dpi=80,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def save_gauge_chart(max_ratio, S_t, output_dir):
    """위험도 게이지 차트 (반원형)."""
    fig, ax = plt.subplots(1, 1, figsize=(7, 4))
    max_ratio_clipped = min(max_ratio, 1.5)

    # 반원 그라데이션 배경 (180도 → 0도)
    theta = np.linspace(np.pi, 0, 100)
    for i, t in enumerate(theta[:-1]):
        sr = i / len(theta) * 1.5
        if sr < 0.7:
            color = "#388E3C"
        elif sr < 1.0:
            color = "#F57C00"
        else:
            color = "#D32F2F"
        ax.plot(
            [np.cos(t), np.cos(theta[i + 1])],
            [np.sin(t), np.sin(theta[i + 1])],
            color=color,
            linewidth=22,
            solid_capstyle="butt",
            alpha=0.8,
        )

    # 바늘 (응력비)
    angle = np.pi - (max_ratio_clipped / 1.5) * np.pi
    needle_x = 0.85 * np.cos(angle)
    needle_y = 0.85 * np.sin(angle)
    ax.plot([0, needle_x], [0, needle_y], color="#0D1B4C", linewidth=4, zorder=5)
    ax.scatter([0], [0], s=300, color="#0D1B4C", zorder=6)
    ax.scatter([0], [0], s=120, color="white", zorder=7)

    # 눈금 라벨
    for sr in [0, 0.5, 0.7, 1.0, 1.5]:
        ang = np.pi - (sr / 1.5) * np.pi
        x, y = 1.18 * np.cos(ang), 1.18 * np.sin(ang)
        ax.text(x, y, f"{sr}", ha="center", va="center", fontsize=11, fontweight="bold")

    # 중앙 텍스트
    if max_ratio < 0.7:
        color = "#388E3C"
    elif max_ratio < 1.0:
        color = "#F57C00"
    else:
        color = "#D32F2F"
    ax.text(
        0,
        -0.45,
        f"SR = {max_ratio:.4f}",
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=color,
    )
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-0.8, 1.4)
    ax.set_aspect("equal")
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(
        os.path.join(output_dir, "gauge.png"),
        dpi=80,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def save_relaxation_curve(props, T_mean, max_stress_ratio, output_dir):
    """응력 이력 곡선 — t_relax (이완시간)에 따른 E_eff 및 응력 변화."""
    times_h = np.linspace(0.5, 12, 50)  # 0.5h ~ 12h
    times_s = times_h * 3600
    E_effs = np.array(
        [effective_relaxation_modulus(props["E"], T_mean, t) for t in times_s]
    )

    # 응력은 E에 비례 → 단순 비례 가정으로 시각화
    E_ref = effective_relaxation_modulus(props["E"], T_mean, 7200.0)
    stress_ratios = max_stress_ratio * (E_effs / E_ref)

    fig, ax1 = plt.subplots(1, 1, figsize=(10, 5))
    color1 = "#1976D2"
    ax1.plot(times_h, E_effs, color=color1, linewidth=2.5, marker="o", markersize=5)
    ax1.set_xlabel("이완 시간 t_relax [hours]", fontsize=12)
    ax1.set_ylabel("유효 탄성계수 E_eff [MPa]", color=color1, fontsize=12)
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.grid(True, alpha=0.3)
    ax1.axvline(2, color="gray", linestyle=":", alpha=0.7, label="기본 (2h)")
    ax1.axvline(6, color="green", linestyle=":", alpha=0.7, label="TSRST 표준 (6h)")

    ax2 = ax1.twinx()
    color2 = "#D32F2F"
    ax2.plot(
        times_h,
        stress_ratios,
        color=color2,
        linewidth=2.5,
        linestyle="--",
        marker="s",
        markersize=5,
    )
    ax2.set_ylabel("예상 응력비 SR", color=color2, fontsize=12)
    ax2.tick_params(axis="y", labelcolor=color2)
    ax2.axhline(1.0, color="red", linestyle="-", alpha=0.4, label="파괴 임계")

    ax1.set_title(
        f"Maxwell 이완 곡선 — 평균온도 {T_mean:.1f}°C 기준",
        fontsize=13,
        fontweight="bold",
    )
    fig.legend(loc="upper right", bbox_to_anchor=(0.88, 0.88), fontsize=10)
    plt.tight_layout()
    plt.savefig(
        os.path.join(output_dir, "relaxation_curve.png"),
        dpi=80,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


# ── [9] 메트릭 + 불확실성 계산 ──────────────────────────────
def compute_detailed_metrics(
    elem_principal,
    risk_map,
    nodes,
    elements,
    pred_mask,
    iou_preds,
    n_rows,
    n_cols,
    props,
):
    total = len(elements)
    critical_count = int(np.sum(risk_map >= 1.0))
    warning_count = int(np.sum((risk_map >= 0.7) & (risk_map < 1.0)))
    safe_count = total - critical_count - warning_count

    worst_idx = int(np.argmax(risk_map))
    worst_center = nodes[elements[worst_idx]].mean(axis=0)
    mesh_w = (n_cols - 1) * 0.01
    mesh_h = (n_rows - 1) * 0.01
    worst_x_pct = float(worst_center[0] / mesh_w * 100)
    worst_y_pct = float((1.0 - worst_center[1] / mesh_h) * 100)

    h, w = pred_mask.shape
    crack_px = int(np.sum(pred_mask > 0))
    crack_ratio = crack_px / float(h * w)

    grade = (
        "Critical" if critical_count > 0 else "Warning" if warning_count > 0 else "Safe"
    )

    # ── 불확실성 정량화: FLIR ONE Pro ±3°C → 응력 변동 ─────
    # σ = E·α·ΔT/(1-ν) 에서 ΔT 변동 ±3°C 적용
    E, nu, alpha, S_t = props["E"], props["nu"], props["alpha"], props["S_t"]
    delta_sigma = E * alpha * 3.0 / (1.0 - nu)  # MPa
    delta_sr = delta_sigma / S_t

    max_stress = float(np.max(np.abs(elem_principal)))
    max_sr = float(risk_map.max())

    return {
        "grade": grade,
        "fem": {
            "max_stress_MPa": round(max_stress, 4),
            "mean_stress_MPa": round(float(np.mean(np.abs(elem_principal))), 4),
            "max_ratio": round(max_sr, 4),
            "median_ratio": round(float(np.median(risk_map)), 4),
            "p90_ratio": round(float(np.percentile(risk_map, 90)), 4),
            "p99_ratio": round(float(np.percentile(risk_map, 99)), 4),
            "critical": critical_count,
            "warning": warning_count,
            "safe": safe_count,
            "total": total,
            "critical_pct": round(critical_count / total * 100, 2),
            "warning_pct": round(warning_count / total * 100, 2),
            "safe_pct": round(safe_count / total * 100, 2),
            "critical_loc_x": round(worst_x_pct, 1),
            "critical_loc_y": round(worst_y_pct, 1),
        },
        "sam2": {
            "crack_pixels": crack_px,
            "crack_ratio": round(crack_ratio, 5),
            "confidence_iou": round(float(iou_preds.flatten()[0].item()), 4),
        },
        "uncertainty": {
            "delta_T_C": 3.0,
            "delta_sigma_MPa": round(delta_sigma, 4),
            "delta_SR": round(delta_sr, 4),
            "stress_range_MPa": [
                round(max_stress - delta_sigma, 4),
                round(max_stress + delta_sigma, 4),
            ],
            "SR_range": [
                round(max(0, max_sr - delta_sr), 4),
                round(max_sr + delta_sr, 4),
            ],
        },
    }


def build_diagnosis_prompt(data, props, verification, scenario_info):
    fem, sam2 = data["fem"], data["sam2"]
    season = (
        "혹한기"
        if props["base_temp"] < 0
        else "환절기" if props["base_temp"] < 15 else "하절기"
    )

    return f"""아래는 도로 포장 열응력 진단 결과 데이터입니다. 이 데이터를 근거로 한국어 종합 진단 보고서를 작성하세요.

[진단 데이터]
- 종합 안전 등급: {data['grade']}
- 측정된 최대 주응력: {fem['max_stress_MPa']} MPa
- 인장강도 대비 응력비: {fem['max_ratio']*100:.1f} 퍼센트
- 위험 요소 개수: {fem['critical']} 개 (전체 {fem['total']} 개 중)
- 균열 픽셀 수: {sam2['crack_pixels']} 픽셀, 전체 면적의 {sam2['crack_ratio']*100:.2f} 퍼센트
- 진단 시점: {props['month']} 월 ({season})
- 해당 월 평균 최저기온: {props['base_temp']}°C
- 적용 인장강도: {props['S_t']} MPa

위 데이터를 보고 한국어로 진단 보고서를 작성하세요. 반드시 아래 5개 섹션 모두 채워서 최소 15문장 이상으로 작성하세요. 영어 단어 한 개로 답하면 안 됩니다.

## 종합 평가
등급과 위험 수준을 한국어 2~3문장으로 평가하세요.

## 위험 분석
응력 분포와 {season} 기온의 영향을 한국어 2~3문장으로 설명하세요.

## 원인 추정
가능한 원인을 한국어 2~3문장으로 추론하세요. 열피로, 포장 노후화, 하부 결함 등을 고려하세요.

## 권고 조치
구체적인 보수 방법을 한국어로 3~4개 항목으로 제시하세요. 크랙실링, 표면처리, 패칭, 오버레이 같은 공법명을 명시하세요.

## 모니터링 주기
다음 점검 시점을 한국어 1~2문장으로 권고하세요.
"""


CHAT_SYSTEM_PROMPT = """당신은 한국도로공사의 아스팔트 포장 진단 전문가입니다.
사용자는 방금 열화상 이미지로 도로 진단을 끝내고 후속 질문을 합니다.

⚠️ 절대 규칙 (위반 시 잘못된 답변):
1. 반드시 한국어 완전한 문장으로 답하세요. 최소 3문장 이상 작성하세요.
2. 단어 하나만 출력하면 안 됩니다. 영어 단어 한 개로 답하면 안 됩니다.
3. 사용자의 질문이 짧거나 영어 단어 하나여도, 그 의도를 한국어로 풀어서 자세히 설명하세요.
4. 'fem'은 유한요소법(Finite Element Method)을 의미합니다. 도로 표면을 작은 격자로 나눠 열응력을 계산하는 수치해석 기법입니다.
5. 응력비가 1.0 이상이면 파괴 위험, 0.7~1.0은 경고, 그 미만은 안전입니다.
6. 데이터에 없는 수치를 만들어내지 마세요.

답변 형식: 항상 한국어 문장으로, 최소 3문장 이상. 단어만 출력 금지."""


# ── [10] API 라우트 ──────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "ok",
        "sam2": sam2_available,
        "ollama": check_ollama_connection(),
        "ollama_model": OLLAMA_MODEL,
        "ollama_model_available": check_ollama_connection(require_model=True),
        "scenarios": list(SCENARIOS.keys()),
        "csv_loader": CSV_LOADER_OK,
    }


def run_analysis(
    image_path,
    output_dir,
    analysis_id,
    capture_date: str | None = None,
    scenario: str = "default",
    mesh_size: int = 40,
    e_override: float | None = None,
    nu_override: float | None = None,
    alpha_override: float | None = None,
    st_override: float | None = None,
):
    """Run inside the resource worker using immutable input and a private output folder."""
    image_path = str(image_path)
    images_dir = Path(output_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    try:
        if not os.path.isfile(image_path):
            raise ValueError("파일이 없습니다. 먼저 이미지를 업로드해주세요.")

        scenario_key = scenario if scenario in SCENARIOS else "default"
        scen = SCENARIOS[scenario_key]
        mesh_size = max(20, min(120, int(mesh_size)))  # 안전 범위

        import torch
        import torch.nn.functional as F
        import cv2

        print(f"[Analyze] 시작 — 시나리오={scenario_key}, 격자={mesh_size}x{mesh_size}")

        # 촬영일 / 물성
        cap_date, cap_src = get_capture_date(image_path, capture_date)
        props = get_material_properties(cap_date)

        # 사용자 물성 오버라이드
        if e_override is not None:
            props["E"] = float(e_override)
        if nu_override is not None:
            props["nu"] = float(nu_override)
        if alpha_override is not None:
            props["alpha"] = float(alpha_override)
        if st_override is not None:
            props["S_t"] = float(st_override)
        print(
            f"[Analyze] 물성: E={props['E']}, ν={props['nu']}, α={props['alpha']:.2e}, S_t={props['S_t']}"
        )

        n_rows = n_cols = mesh_size

        # 입력 모드 결정 (CSV 자동 감지)
        ext = os.path.splitext(image_path)[1].lower()
        input_mode = (
            "csv_absolute" if (ext == ".csv" and CSV_LOADER_OK) else "png_grayscale"
        )
        print(f"[Analyze] 입력 모드: {input_mode}")

        # ── SAM2 추론 (CSV 입력이면 시각화용 임시 PNG 생성) ──
        if input_mode == "csv_absolute":
            T_csv, csv_meta = csv_to_temperature(image_path, n_rows, n_cols)
            # CSV는 SAM2 검출이 의미 약함 → 빈 마스크 사용 + 시각화용 가짜 이미지
            T_full, _ = csv_to_temperature(image_path, 480, 640)
            norm = (T_full - T_full.min()) / (T_full.max() - T_full.min() + 1e-9)
            image_np = (plt.get_cmap("inferno")(norm)[:, :, :3] * 255).astype(np.uint8)
            pred_mask = np.zeros((480, 640), dtype=np.uint8)
            expanded_mask = np.zeros((480, 640), dtype=np.uint8)
            iou_preds = torch.tensor([[0.0]])
            T_image = T_csv  # 절대온도 그대로 사용
            print(
                f"[Analyze] CSV 절대온도 입력: T={T_csv.min():.1f}~{T_csv.max():.1f}°C"
            )
        else:
            print("[Analyze] SAM2 추론 중...")
            if not sam2_available:
                raise RuntimeError("SAM2 모델을 사용할 수 없습니다. 서버 로그를 확인하세요.")
            with PILImage.open(image_path) as source:
                image_pil = source.convert("RGB")
            # ★ 속도 개선: 큰 이미지는 미리 축소 (SAM2가 어차피 1024로 리사이즈하므로)
            if max(image_pil.size) > 1280:
                image_pil.thumbnail((1280, 1280), PILImage.LANCZOS)
                print(f"[Analyze] 이미지 축소: {image_pil.size}")
            image_np = np.array(image_pil)
            image_tensor = sam_transform(image_pil).unsqueeze(0).to(DEVICE)
            with torch.no_grad():
                low_res_masks, iou_preds = tuner(image_tensor)
            h, w = image_np.shape[:2]
            pred_mask = (
                (F.interpolate(low_res_masks, size=(h, w), mode="bilinear") > 0.0)
                .cpu()
                .numpy()[0, 0]
                .astype(np.uint8)
            )
            expanded_mask = apply_morphological_dilation(
                pred_mask, dilation_radius=7, binarization_threshold=0
            )

            thermal_img = (
                cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
                if image_np.ndim == 3
                else image_np
            )
            thermal_matrix = np.full(thermal_img.shape, np.nan, dtype=np.float32)
            thermal_matrix[expanded_mask > 0] = thermal_img[expanded_mask > 0].astype(
                np.float32
            )

            # 픽셀 → 온도 매핑 (PNG 폴백: 월별 base_temp 기준 ±10°C)
            filled = np.nan_to_num(
                thermal_matrix,
                nan=(
                    np.nanmean(thermal_matrix)
                    if np.any(np.isfinite(thermal_matrix))
                    else 128
                ),
            )
            T_raw = np.array(
                PILImage.fromarray(filled.astype(np.uint8)).resize((n_cols, n_rows)),
                dtype=float,
            )
            T_image = (
                props["base_temp"]
                + (T_raw - T_raw.min()) / (T_raw.max() - T_raw.min() + 1e-9) * 20.0
            )

        # CSV 모드의 파이프라인에는 절대온도 행렬 사용
        if input_mode == "csv_absolute":
            thermal_matrix = T_full.astype(np.float32)

        # ── FEM 해석 ──
        print(
            f"[Analyze] FEM ({n_rows}x{n_cols}, BC={scen['bc']}, wk={scen['wk']:.1e}, tr={scen['tr']:.0f}s)"
        )
        prep = ThermalPreprocessor(n_rows, n_cols)
        T_image = prep.correct(T_image)
        nodes, elements = generate_cst_mesh(n_rows, n_cols)
        d_global, elem_stresses, elem_principal = assemble_and_solve(
            nodes,
            elements,
            T_image.flatten(),
            props,
            bc_mode=scen["bc"],
            winkler_k=scen["wk"],
            t_relax=scen["tr"],
        )
        risk_map = compute_risk_map(elem_principal, props["S_t"])

        # ── 메트릭 + 검증 + 시각화 ──
        metrics = compute_detailed_metrics(
            elem_principal,
            risk_map,
            nodes,
            elements,
            pred_mask,
            iou_preds,
            n_rows,
            n_cols,
            props,
        )

        # ── ★ V1 검증: 항상 fully_fixed BC로 별도 계산 ──
        # 사용자 시나리오와 무관하게 V1 이론해(σ=E·α·ΔT/(1-ν), 완전구속)와의
        # 수치해 정확도를 검증하기 위해 nodes/elements/bc_mode를 전달.
        # 이렇게 해야 verification_suite 내부에서 ΔT=15°C 균일 가상 온도장 +
        # fully_fixed BC로 재계산하여 진짜 V1 검증이 수행됨.
        verification = verification_suite(
            props,
            elem_principal,
            risk_map,
            nodes=nodes,
            elements=elements,
            bc_mode="fully_fixed",  # ★ V1 검증용 BC 강제 지정
            t_relax=7200.0,
        )

        try:
            save_pipeline_image(
                image_np, expanded_mask, thermal_matrix, risk_map, nodes, elements,
                images_dir,
            )
            visualize_results(
                nodes,
                elements,
                T_image.flatten(),
                elem_principal,
                risk_map,
                n_rows,
                n_cols,
                props,
                out=str(images_dir),
            )
            save_risk_overlay(image_np, risk_map, nodes, elements, n_rows, n_cols, images_dir)
            save_donut_chart(
                metrics["fem"]["critical"],
                metrics["fem"]["warning"],
                metrics["fem"]["safe"],
                metrics["fem"]["total"],
                images_dir,
            )
            save_gauge_chart(metrics["fem"]["max_ratio"], props["S_t"], images_dir)
        except Exception as ve:
            print(f"[Analyze] 시각화 일부 실패(무시): {ve}")

        analysis = {
            "analysis_id": analysis_id,
            "images": {
                image.name: f"/analyses/{analysis_id}/images/{image.name}"
                for image in images_dir.glob("*.png")
            },
            "result": metrics,
            "scenario": scenario_key,
            "scenario_info": {"name": scen["name"], "desc": scen["desc"]},
            "mesh_resolution": f"{n_rows}x{n_cols}",
            "input_mode": input_mode,
            "capture_date": cap_date,
            "capture_date_source": cap_src,
            "props": {
                "month": int(props["month"]),
                "base_temp": float(props["base_temp"]),
                "E": float(props["E"]),
                "nu": float(props["nu"]),
                "alpha": float(props["alpha"]),
                "S_t": float(props["S_t"]),
            },
            "verification": {
                k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                for k, v in verification.items()
            },
        }
        print(
            f"[Analyze] 완료 — 등급={metrics['grade']}, 최대 SR={metrics['fem']['max_ratio']}"
        )
        return analysis

    except Exception as ex:
        err_detail = traceback.format_exc()
        print(f"[Analyze] 예외:\n{err_detail}")
        raise RuntimeError(f"분석 실패: {ex}") from ex
    finally:
        # Matplotlib is used only by this worker. Release failed and completed figures.
        plt.close("all")


@app.get("/scenarios")
def get_scenarios():
    return SCENARIOS


def run_diagnosis(analysis, output_dir):
    prompt = build_diagnosis_prompt(
        analysis["result"], analysis["props"], analysis["verification"],
        analysis["scenario_info"],
    )
    diagnosis = call_ollama(prompt, timeout=600, num_predict=600)
    if diagnosis.startswith(("❌", "⚠")):
        raise RuntimeError(diagnosis)
    (Path(output_dir) / "diagnosis.txt").write_text(diagnosis, encoding="utf-8")
    return {"diagnosis": diagnosis}


def run_chat(analysis, message, output_dir):
    user_msg = message.strip()
    print(f"[Chat] {user_msg[:80]}")
    if not user_msg:
        return {"reply": "질문을 입력해주세요."}

    if analysis:
        m, props = analysis["result"], analysis["props"]
        season = (
            "혹한기"
            if props["base_temp"] < 0
            else "환절기" if props["base_temp"] < 15 else "하절기"
        )
        context = (
            f"[직전 분석 결과]\n"
            f"- 등급: {m['grade']}\n"
            f"- 최대 응력: {m['fem']['max_stress_MPa']} MPa (SR={m['fem']['max_ratio']*100:.1f}%)\n"
            f"- Critical {m['fem']['critical']}개 / 전체 {m['fem']['total']}개\n"
            f"- 균열: {m['sam2']['crack_pixels']}px\n"
            f"- 진단월: {props['month']}월 ({season}, {props['base_temp']}°C)\n\n"
        )
    else:
        context = "[안내] 아직 이미지 분석이 안 됐습니다.\n\n"

    full_prompt = (
        context + f"[질문]\n{user_msg}\n\n"
        f"위 결과를 참고해 한국어 3~5문장으로 답하세요."
    )

    reply = call_ollama(
        full_prompt, timeout=120, num_predict=300, system=CHAT_SYSTEM_PROMPT
    )
    if reply.startswith(("❌", "⚠")):
        raise RuntimeError(reply)
    (Path(output_dir) / "chat.json").write_text(
        json.dumps({"analysis_id": analysis["analysis_id"], "message": user_msg,
                    "reply": reply}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"reply": reply}


# ── Session/job API ─────────────────────────────────────────
@app.exception_handler(JobError)
async def handle_job_error(request, exc):
    return JSONResponse(
        status_code=exc.status_code, content={"error": str(exc), "detail": str(exc)},
        headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def private_response_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def require_session(x_soc_session: str | None = Header(default=None)):
    return job_manager.validate_session(x_soc_session)


@app.post("/session", status_code=201)
def create_session():
    return {"session_id": job_manager.create_session(), "expires_in": SESSION_TTL_SECONDS}


@app.post("/upload", status_code=201)
def upload(file: UploadFile = File(...), session_id: str = Depends(require_session)):
    """Upload in a threadpool so local disk I/O never blocks the ASGI event loop."""
    name = os.path.basename((file.filename or "upload.bin").replace("\\", "/"))
    suffix = Path(name).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".csv"}:
        raise HTTPException(415, "JPG, PNG, TIFF, BMP 이미지 또는 CSV 파일을 올려주세요.")
    limit = MAX_UPLOAD_MB * 1024 * 1024
    if file.size is not None and file.size > limit:
        raise HTTPException(413, f"파일은 {MAX_UPLOAD_MB} MB 이하로 올려주세요.")
    upload_id, path = job_manager.begin_upload(session_id, suffix)
    success = False
    try:
        total = 0
        with path.open("xb") as target:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, f"파일은 {MAX_UPLOAD_MB} MB 이하로 올려주세요.")
                target.write(chunk)
        if total == 0:
            raise HTTPException(400, "빈 파일은 업로드할 수 없습니다.")
        if suffix != ".csv":
            try:
                with PILImage.open(path) as image:
                    image.verify()
            except Exception as exc:
                raise HTTPException(400, "이미지 파일을 읽을 수 없습니다.") from exc
        success = True
        return {"status": "uploaded", "upload_id": upload_id, "name": name,
                "ext": suffix, "size": total}
    finally:
        try:
            if not success:
                path.unlink(missing_ok=True)
        finally:
            job_manager.finish_upload(session_id, upload_id, success=success)


class AnalyzeRequest(BaseModel):
    upload_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    capture_date: str | None = None
    scenario: Literal["default", "v1", "v2", "v3"] = "default"
    mesh_size: int = Field(default=40, ge=20, le=120)
    e_override: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    nu_override: float | None = Field(default=None, ge=0, lt=0.5, allow_inf_nan=False)
    alpha_override: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    st_override: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)

    @field_validator("capture_date")
    @classmethod
    def valid_date(cls, value):
        if value:
            return date.fromisoformat(value).isoformat()
        return None


class DiagnosisRequest(BaseModel):
    analysis_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ChatRequest(DiagnosisRequest):
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value):
        if not value.strip():
            raise ValueError("질문을 입력해주세요.")
        return value.strip()


@app.post("/jobs/analyze", status_code=202)
def enqueue_analysis(request: AnalyzeRequest, session_id: str = Depends(require_session)):
    image_path = job_manager.upload_path(session_id, request.upload_id)
    parameters = request.model_dump(exclude={"upload_id"})
    return job_manager.submit(
        session_id, "analyze",
        lambda job_id, directory: run_analysis(image_path, directory, job_id, **parameters),
    )


@app.post("/jobs/diagnose", status_code=202)
def enqueue_diagnosis(request: DiagnosisRequest, session_id: str = Depends(require_session)):
    analysis = job_manager.analysis(session_id, request.analysis_id)
    return job_manager.submit(
        session_id, "diagnose",
        lambda job_id, directory: run_diagnosis(analysis, directory),
    )


@app.post("/jobs/chat", status_code=202)
def enqueue_chat(request: ChatRequest, session_id: str = Depends(require_session)):
    analysis = job_manager.analysis(session_id, request.analysis_id)
    return job_manager.submit(
        session_id, "chat",
        lambda job_id, directory: run_chat(analysis, request.message, directory),
    )


@app.get("/jobs/{job_id}")
def get_job(job_id: str, session_id: str = Depends(require_session)):
    return job_manager.get_job(session_id, job_id)


@app.get("/analyses/{analysis_id}/images/{filename}")
def get_analysis_image(analysis_id: str, filename: str,
                       session_id: str = Depends(require_session)):
    path = job_manager.analysis_image(session_id, analysis_id, filename)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
