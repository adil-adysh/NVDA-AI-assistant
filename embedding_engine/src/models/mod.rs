pub mod granite;
pub mod harrier;
pub mod minilm;

use anyhow::Result;
use std::path::Path;
use tokenizers::{Tokenizer, TruncationParams};

fn load_tokenizer(path: &Path, max_length: usize) -> Result<Tokenizer> {
    let mut tokenizer = Tokenizer::from_file(path).map_err(|error| anyhow::anyhow!("{error}"))?;
    let truncation = TruncationParams { max_length, ..Default::default() };
    tokenizer.with_truncation(Some(truncation)).map_err(|error| anyhow::anyhow!("{error}"))?;
    tokenizer.with_padding(None);
    Ok(tokenizer)
}
