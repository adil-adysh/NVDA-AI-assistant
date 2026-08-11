//! Attention-mask-aware pooling and L2 normalization.
//!
//! Supports multiple pooling strategies shared across embedding models:
//!   - mean_pool: SBERT-style mean over token embeddings (MiniLM, BGE, E5)
//!   - cls_pool:   first-token ([CLS]) pooling (Granite, ModernBERT)
//!   - last_token_pool: last non-padding token (Harrier, Gemma3 decoder)

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

/// Extract the first token (CLS) from `(batch, seq_len, hidden)` embeddings.
///
/// Used by ModernBERT / Granite embedding models that use CLS pooling.
pub fn cls_pool(token_embeddings: &Tensor) -> Result<Tensor> {
    // token_embeddings shape: (batch, seq_len, hidden)
    // Take the first token: (batch, hidden)
    token_embeddings
        .get_on_dim(1, 0)
        .map_err(|e| anyhow::anyhow!("cls_pool get_on_dim: {e}"))
}

/// Extract the last non-padding token from `(batch, seq_len, hidden)` embeddings.
///
/// Finds the last position where attention_mask == 1 for each sequence,
/// and extracts the corresponding hidden state.  Used by decoder models
/// (Harrier / Gemma3) where the last meaningful token carries the embedding.
pub fn last_token_pool(
    token_embeddings: &Tensor,
    attention_mask: &Tensor,
) -> Result<Tensor> {
    let (_batch_size, seq_len, _hidden_dim) = token_embeddings.dims3()
        .map_err(|e| anyhow::anyhow!("last_token_pool dims3: {e}"))?;

    // Find the index of the last non-padded token for each row:
    // last_idx[b] = sum(mask[b,:]) - 1
    let seq_lens = attention_mask
        .sum(1)
        .map_err(|e| anyhow::anyhow!("last_token_pool sum: {e}"))?;
    // shape: (batch, 1)
    let seq_lens = seq_lens
        .broadcast_sub(&Tensor::new(&[1f32], attention_mask.device())
            .map_err(|e| anyhow::anyhow!("last_token_pool sub scalar: {e}"))?)
        .map_err(|e| anyhow::anyhow!("last_token_pool sub: {e}"))?;
    // Clamp negative (all-zero rows) to 0
    let seq_lens = seq_lens
        .clamp(0f64, (seq_len - 1) as f64)
        .map_err(|e| anyhow::anyhow!("last_token_pool clamp: {e}"))?;
    // Convert to u32 indices
    let seq_lens_u32 = seq_lens
        .to_dtype(candle_core::DType::U32)
        .map_err(|e| anyhow::anyhow!("last_token_pool to_dtype: {e}"))?;
    let indices: Vec<u32> = seq_lens_u32.flatten_all()
        .map_err(|e| anyhow::anyhow!("last_token_pool flatten: {e}"))?
        .to_vec1()
        .map_err(|e| anyhow::anyhow!("last_token_pool to_vec1: {e}"))?;

    // Gather the last token for each batch item
    let batch_size = indices.len();
    let mut rows = Vec::with_capacity(batch_size);
    for (b, &idx) in indices.iter().enumerate() {
        let row = token_embeddings
            .get(b)
            .map_err(|e| anyhow::anyhow!("last_token_pool get batch {b}: {e}"))?
            .get(idx as usize)
            .map_err(|e| anyhow::anyhow!("last_token_pool get idx {idx}: {e}"))?;
        rows.push(row);
    }
    let pooled = Tensor::stack(&rows.iter().map(|t| t as &Tensor).collect::<Vec<_>>(), 0)
        .map_err(|e| anyhow::anyhow!("last_token_pool stack: {e}"))?;

    Ok(pooled)
}

/// CLS pool + L2 normalize (Granite-style pipeline).
pub fn cls_pool_and_normalize(token_embeddings: &Tensor) -> Result<Tensor> {
    let pooled = cls_pool(token_embeddings)
        .map_err(|e| anyhow::anyhow!("cls_pool failed: {e}"))?;
    l2_normalize(&pooled)
        .map_err(|e| anyhow::anyhow!("l2_normalize failed: {e}"))
}

/// Last-token pool + L2 normalize (Harrier-style pipeline).
pub fn last_token_pool_and_normalize(
    token_embeddings: &Tensor,
    attention_mask: &Tensor,
) -> Result<Tensor> {
    let pooled = last_token_pool(token_embeddings, attention_mask)
        .map_err(|e| anyhow::anyhow!("last_token_pool failed: {e}"))?;
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
