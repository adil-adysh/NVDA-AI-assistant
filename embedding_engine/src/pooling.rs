//! Attention-mask-aware mean pooling and L2 normalization.
//!
//! These functions are shared across all BERT-derived embedding models
//! that use mean pooling (MiniLM, BGE, E5, etc.).

use anyhow::Result;
use candle_core::Tensor;

/// Compute attention-mask-aware mean pooling over token embeddings.
///
/// Takes the full `(batch, seq_len, hidden)` token embeddings and an
/// `(batch, seq_len)` attention mask.  Zero-masked positions are excluded
/// from the mean.  Returns `(batch, hidden)` pooled embeddings.
///
/// Reference: sentence-transformers / SBERT mean pooling:
/// <https://github.com/UKPLab/sentence-transformers/blob/master/sentence_transformers/models/Pooling.py>
pub fn mean_pool(
    token_embeddings: &Tensor,
    attention_mask: &Tensor,
) -> Result<Tensor> {
    let (_batch_size, _seq_len, _hidden_dim) = token_embeddings.dims3()
        .map_err(|e| anyhow::anyhow!("dims3: {e}"))?;

    // Expand mask to (batch, seq_len, 1)
    let mask: Tensor = attention_mask
        .unsqueeze(2)
        .map_err(|e| anyhow::anyhow!("unsqueeze mask: {e}"))?
        .to_dtype(token_embeddings.dtype())
        .map_err(|e| anyhow::anyhow!("to_dtype mask: {e}"))?;

    // Sum of masked token embeddings: (batch, hidden)
    let masked = token_embeddings.broadcast_mul(&mask)
        .map_err(|e| anyhow::anyhow!("mul mask: {e}"))?;
    let sum: Tensor = masked.sum(1)
        .map_err(|e| anyhow::anyhow!("sum: {e}"))?;

    // Count of non-masked tokens per sample: (batch, 1)
    let count: Tensor = mask.sum(1)
        .map_err(|e| anyhow::anyhow!("count sum: {e}"))?;

    // Mean: divide sum by count, clamping to avoid division by zero
    let count_clamped = count.clamp(1e-9, f64::MAX)
        .map_err(|e| anyhow::anyhow!("clamp count: {e}"))?;
    let pooled: Tensor = sum.broadcast_div(&count_clamped)
        .map_err(|e| anyhow::anyhow!("broadcast_div (mean): {e}"))?;

    Ok(pooled)
}

/// L2-normalize embedding vectors along the last dimension.
///
/// Returns `(batch, dim)` with each row having unit L2 norm.
pub fn l2_normalize(embeddings: &Tensor) -> Result<Tensor> {
    let eps: f64 = 1e-12;
    let squared: Tensor = embeddings.sqr().map_err(|e| anyhow::anyhow!("sqr: {e}"))?;
    let sum_squares: Tensor = squared.sum_keepdim(1).map_err(|e| anyhow::anyhow!("sum_keepdim: {e}"))?;
    let norms: Tensor = (sum_squares + eps).map_err(|e| anyhow::anyhow!("add eps: {e}"))?;
    let norms: Tensor = norms.sqrt().map_err(|e| anyhow::anyhow!("sqrt: {e}"))?;
    let normalized: Tensor = embeddings.broadcast_div(&norms).map_err(|e| anyhow::anyhow!("broadcast_div: {e}"))?;
    Ok(normalized)
}

/// Full MiniLM/BGE/E5 embedding pipeline: token embeddings → mean pool → L2 normalize.
pub fn pool_and_normalize(
    token_embeddings: &Tensor,
    attention_mask: &Tensor,
) -> Result<Tensor> {
    let pooled = mean_pool(token_embeddings, attention_mask)
        .map_err(|e| anyhow::anyhow!("mean_pool failed: {e}"))?;
    l2_normalize(&pooled)
        .map_err(|e| anyhow::anyhow!("l2_normalize failed: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use candle_core::Device;

    #[test]
    fn test_mean_pool_mask() {
        let dev = Device::Cpu;

        // Single sequence of length 4, hidden dim 3.
        // Weights: positions 0-3 have values 1.0..4.0
        // Mask:   [1, 1, 0, 1]  → only positions 0, 1, 3 used
        let token_emb = Tensor::from_vec(
            vec![
                1.0f32, 2.0, 3.0, // pos 0
                4.0, 5.0, 6.0, // pos 1
                7.0, 8.0, 9.0, // pos 2 (masked out)
                10.0, 11.0, 12.0, // pos 3
            ],
            (1, 4, 3),
            &dev,
        )
        .unwrap();

        let mask = Tensor::from_vec(vec![1.0f32, 1.0, 0.0, 1.0], (1, 4), &dev).unwrap();

        let pooled = mean_pool(&token_emb, &mask).unwrap();
        let result: Vec<f32> = pooled.flatten_all().unwrap().to_vec1().unwrap();

        // Expected: mean of pos 0, 1, 3 = ((1+4+10)/3, (2+5+11)/3, (3+6+12)/3) = (5, 6, 7)
        assert!((result[0] - 5.0).abs() < 0.001);
        assert!((result[1] - 6.0).abs() < 0.001);
        assert!((result[2] - 7.0).abs() < 0.001);
    }

    #[test]
    fn test_l2_normalize() {
        let dev = Device::Cpu;
        // Vector [3, 4] has norm = 5 → after L2: [0.6, 0.8]
        let emb = Tensor::from_vec(vec![3.0f32, 4.0], (1, 2), &dev).unwrap();
        let normalized = l2_normalize(&emb).unwrap();
        let result: Vec<f32> = normalized.flatten_all().unwrap().to_vec1().unwrap();
        assert!((result[0] - 0.6).abs() < 0.001);
        assert!((result[1] - 0.8).abs() < 0.001);
    }

    #[test]
    fn test_pool_and_normalize_unit_norm() {
        let dev = Device::Cpu;
        let token_emb = Tensor::ones((2, 5, 8), candle_core::DType::F32, &dev).unwrap();
        let mask = Tensor::ones((2, 5), candle_core::DType::F32, &dev).unwrap();
        let normalized = pool_and_normalize(&token_emb, &mask).unwrap();
        let result: Vec<f32> = normalized.flatten_all().unwrap().to_vec1().unwrap();

        // Each of the 2 rows should have L2 norm ≈ 1.0
        assert_eq!(result.len(), 16); // 2 × 8
        let row0_norm: f32 = result[..8].iter().map(|v| v * v).sum::<f32>().sqrt();
        let row1_norm: f32 = result[8..].iter().map(|v| v * v).sum::<f32>().sqrt();
        assert!((row0_norm - 1.0).abs() < 0.001);
        assert!((row1_norm - 1.0).abs() < 0.001);
    }
}
