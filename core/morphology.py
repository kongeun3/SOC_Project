import numpy as np
import cv2


def build_disk_kernel(radius: int) -> np.ndarray:
    """
    반경 r인 원형 구조요소 K_r 생성
    K_r = { (i,j) | i^2+j^2 <= r^2 }

    Args:
        radius (int): 구조요소의 반경 (픽셀 단위)

    Returns:
        np.ndarray: 원형 구조요소 (uint8)
    """
    if radius < 1:
        raise ValueError(f"radius는 1 이상의 정수여야 합니다. (입력값: {radius})")

    y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (x**2 + y**2 <= radius**2).astype(np.uint8)


def apply_morphological_dilation(
    pred_mask: np.ndarray,
    dilation_radius: int = 3,
    binarization_threshold: int = 127,
) -> np.ndarray:
    """
    pred_mask에 morphological dilation을 적용합니다.

    Args:
        pred_mask (np.ndarray): 입력 마스크 (uint8, 0-255 범위)
        dilation_radius (int): 구조요소의 반경 (기본값: 3)
        binarization_threshold (int): 이진화 임계값 (기본값: 127)

    Returns:
        np.ndarray: Dilation이 적용된 확장 마스크 (uint8, 0-255 범위)

    Example:
        >>> pred_mask = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
        >>> expanded_mask = apply_morphological_dilation(pred_mask, dilation_radius=1)
    """

    if not isinstance(pred_mask, np.ndarray):
        raise TypeError(
            f"pred_mask는 numpy array여야 합니다. (입력값: {type(pred_mask)})"
        )

    if len(pred_mask.shape) != 2:
        raise ValueError(
            f"pred_mask는 2D array여야 합니다. (입력값: shape={pred_mask.shape})"
        )

    _, binary_mask = cv2.threshold(
        pred_mask, binarization_threshold, 255, cv2.THRESH_BINARY
    )

    kernel = build_disk_kernel(dilation_radius)

    expanded_mask = cv2.dilate(binary_mask, kernel, iterations=1)

    return expanded_mask
