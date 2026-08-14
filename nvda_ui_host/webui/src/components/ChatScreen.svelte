<script>
    import { appState, t } from '../lib/state.svelte';
    import ChatPanel from './ChatPanel.svelte';
    import MessageItem from './MessageItem.svelte';

    let { registerContent = () => {} } = $props();
    let contentElement = $state(null);
    let isSelectedConversationEmpty = $derived(
        appState.chat.conversationSelectionState === 'selected_empty',
    );

    $effect(() => {
        registerContent(contentElement);
        return () => registerContent(null);
    });
</script>

<ChatPanel />

<section class="workspace-card content-card chat-screen" aria-labelledby="chat-content-heading">
    <h2 id="chat-content-heading" class="section-title">{t('chat_content_heading', 'Conversation')}</h2>
    <div id="content" bind:this={contentElement} role="region" tabindex="-1">
        {#if appState.chat.transcript.messages.length === 0}
            {#if isSelectedConversationEmpty}
                {t('selected_conversation_empty', 'This conversation has no messages yet.')}
            {:else}
                {t('no_chat_messages', 'No messages yet. Start the conversation by typing a message below.')}
            {/if}
        {:else}
            <div
                class="chat-transcript"
                role="log"
                aria-live="off"
                aria-label={t('chat_transcript_label', 'Chat messages')}
            >
                {#each appState.chat.transcript.messages as message (message.id || `${message.role}-${message.content}`)}
                    <MessageItem {message} />
                {/each}
            </div>
        {/if}
    </div>
</section>
