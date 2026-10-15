import torch
import torch.nn as nn

from sam2.build_sam import build_sam2


class SAM2PromptTuner(nn.Module):
    def __init__(self, model_cfg, sam2_checkpoint, num_tokens=10):
        super().__init__()
        self.sam2 = build_sam2(
            model_cfg,
            sam2_checkpoint,
            device="cuda:0" if torch.cuda.is_available() else "cpu",
        )
        for param in self.sam2.parameters():
            param.requires_grad = False
        self.sam2.eval()
        self.learnable_sparse_embeddings = nn.Parameter(torch.randn(1, num_tokens, 256))
        self.not_a_mask_embed = nn.Parameter(torch.zeros(1, 256, 64, 64))

    def forward(self, x):
        with torch.no_grad():
            backbone_out = self.sam2.forward_image(x)
            image_embeddings = backbone_out["backbone_fpn"][-1]
            high_res_features = backbone_out["backbone_fpn"][:-1]
            image_pe = self.sam2.sam_prompt_encoder.get_dense_pe()

        B = x.shape[0]
        sparse_prompts = self.learnable_sparse_embeddings.expand(B, -1, -1)
        dense_prompts = self.not_a_mask_embed.expand(B, -1, -1, -1)

        low_res_masks, iou_predictions, _, _ = self.sam2.sam_mask_decoder(
            image_embeddings=image_embeddings,
            image_pe=image_pe,
            sparse_prompt_embeddings=sparse_prompts,
            dense_prompt_embeddings=dense_prompts,
            multimask_output=False,
            repeat_image=False,
            high_res_features=high_res_features,
        )
        return low_res_masks, iou_predictions
