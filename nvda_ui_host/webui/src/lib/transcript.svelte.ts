import type { ChatMessage, ContentBlock } from './protocol-types';

/**
 * Owns chat message lifecycle: ordering, deduplication, streaming state.
 *
 * Reactive by construction — `_messages` is a Svelte 5 $state array.
 * No external $state wrapping needed.
 */
export class Transcript {
	private _messages: ChatMessage[] = $state([]);

	// ------------------------------------------------------------------
	// Read
	// ------------------------------------------------------------------

	get messages(): readonly ChatMessage[] {
		return this._messages;
	}

	get count(): number {
		return this._messages.length;
	}

	findById(id: string): ChatMessage | undefined {
		return this._messages.find((m) => m.id === id);
	}

	// ------------------------------------------------------------------
	// Bulk
	// ------------------------------------------------------------------

	setHistory(messages: ChatMessage[]): void {
		this._messages = [...messages];
		console.log(`[Transcript] setHistory: stored ${this._messages.length} messages`);
	}

	clear(): void {
		this._messages = [];
	}

	// ------------------------------------------------------------------
	// Single message
	// ------------------------------------------------------------------

	/** Insert or replace by id. */
	upsert(message: ChatMessage): void {
		this._messages = this._messages.filter((m) => m.id !== message.id);
		this._messages.push(message);
		console.log(`[Transcript] upsert: id=${message.id} role=${message.role} count=${this._messages.length}`);
	}

	/** Append without dedup (caller guarantees no collision). */
	append(message: ChatMessage): void {
		this._messages.push(message);
	}

	upsertMany(messages: ChatMessage[]): void {
		for (const msg of messages) {
			this.upsert(msg);
		}
	}

	updateMessage(id: string, updater: (msg: ChatMessage) => ChatMessage): boolean {
		const idx = this._messages.findIndex((m) => m.id === id);
		if (idx < 0) return false;
		this._messages[idx] = updater(this._messages[idx]);
		return true;
	}

	// ------------------------------------------------------------------
	// Streaming lifecycle
	// ------------------------------------------------------------------

	/**
	 * Create or reset a streaming placeholder.
	 * Returns the placeholder message.
	 */
	beginStream(
		messageId: string,
		streamId: string,
		role: string = 'assistant',
		initialContent: ContentBlock[] = [],
	): ChatMessage {
		const existing = this.findById(messageId);

		const placeholder: ChatMessage = existing
			? {
					...existing,
					role: (role || existing.role || 'assistant') as ChatMessage['role'],
					content:
						existing.streamId === streamId ? existing.content : initialContent,
					streaming: true,
					streamId,
					streamSequence:
						existing.streamId === streamId
							? (existing.streamSequence ?? -1)
							: -1,
					streamAborted: false,
				}
			: {
					id: messageId,
					role: (role || 'assistant') as ChatMessage['role'],
					content: initialContent,
					streaming: true,
					streamId,
					streamSequence: -1,
				};

		this.upsert(placeholder);
		return placeholder;
	}

	/**
	 * Apply a text delta to a streaming message.
	 * Respects sequence ordering — out-of-order deltas are silently dropped.
	 */
	applyDelta(
		messageId: string,
		streamId: string,
		delta: string,
		sequence: number,
	): boolean {
		const msg = this.findById(messageId);
		if (!msg || msg.streamId !== streamId || msg.streaming !== true) {
			return false;
		}

		const currentSeq = Number.isInteger(msg.streamSequence)
			? (msg.streamSequence as number)
			: -1;
		if (sequence <= currentSeq) return false;

		const contentBlocks: ContentBlock[] = Array.isArray(msg.content)
			? [...msg.content]
			: [];
		const textIdx = contentBlocks.findIndex((b) => b.type === 'text');

		if (textIdx >= 0) {
			const currentText =
				typeof (contentBlocks[textIdx] as { text?: string }).text === 'string'
					? (contentBlocks[textIdx] as { text: string }).text
					: '';
			contentBlocks[textIdx] = { type: 'text', text: currentText + delta };
		} else {
			contentBlocks.unshift({ type: 'text', text: delta });
		}

		return this.updateMessage(messageId, (m) => ({
			...m,
			content: contentBlocks,
			streamSequence: sequence,
		}));
	}

	endStream(messageId: string, streamId: string): boolean {
		const msg = this.findById(messageId);
		if (!msg || msg.streamId !== streamId) return false;

		return this.updateMessage(messageId, (m) => ({
			...m,
			streaming: false,
			streamId: null,
		}));
	}

	abortStream(messageId: string, streamId: string): boolean {
		const msg = this.findById(messageId);
		if (!msg || msg.streamId !== streamId) return false;

		return this.updateMessage(messageId, (m) => ({
			...m,
			streaming: false,
			streamAborted: true,
			streamId: null,
		}));
	}
}
