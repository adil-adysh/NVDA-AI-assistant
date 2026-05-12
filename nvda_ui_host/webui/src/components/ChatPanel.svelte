<script>
    import { appState, t } from '../lib/state.svelte';
    import ConversationSidebar from './ConversationSidebar.svelte';

    let { } = $props();
    let sidebarCollapsed = $state(false);

    let activeConversation = $derived(
        appState.chat.conversations.find(conversation => conversation.id === appState.chat.conversationId) ?? null
    );

    function toggleConversationSidebar() {
        sidebarCollapsed = !sidebarCollapsed;
    }
</script>

{#if appState.view.mode === 'chat'}
    <section id="chat-panel" class="workspace-card chat-panel" aria-label={t('chat_heading', 'Chat')}>
        <div class="chat-navigation-stack">
            {#if activeConversation}
                <div class="chat-session-banner" aria-live="polite">
                    <span class="chat-session-label">{t('current_conversation_label', 'Current conversation')}</span>
                    <strong class="chat-session-title">{activeConversation.title}</strong>
                </div>
            {/if}

            <ConversationSidebar collapsed={sidebarCollapsed} onToggle={toggleConversationSidebar} />
        </div>
    </section>
{/if}
