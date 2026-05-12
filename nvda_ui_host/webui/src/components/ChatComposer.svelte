<script>
    import { focusChatComposer, submitChatMessage } from '../lib/actions.js';
    import { handleFileSelection } from '../lib/attachments.js';
    import { appState, t } from '../lib/state.svelte.js';
    import AttachmentStrip from './AttachmentStrip.svelte';

    let { registerComposer = () => {}, registerFileInput = () => {} } = $props();

    let composerElement = $state(null);
    let fileInputElement = $state(null);

    $effect(() => {
        registerComposer(composerElement);
    });

    $effect(() => {
        registerFileInput(fileInputElement);
    });

    async function handleInputFiles(event) {
        await handleFileSelection(event.currentTarget.files);
    }

    function handleKeydown(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submitChatMessage(fileInputElement);
        }
    }

    let chatDisabled = $derived(!appState.control.chatEnabled || Boolean(appState.control.pendingChange));
</script>

{#if appState.view.mode === 'chat'}
    <section class="workspace-card chat-composer-panel" aria-labelledby="chat-composer-heading">
        <div class="section-header">
            <h2 id="chat-composer-heading" class="section-title">{t('chat_heading', 'Chat')}</h2>
        </div>

        <div class="composer-stack">
            <input id="file-input" bind:this={fileInputElement} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.bmp,.svg" multiple hidden onchange={handleInputFiles} />

            <AttachmentStrip />

            <label class="composer-field" for="chat-input">
                <span class="composer-label">{t('message_label', 'Message')}</span>
                <textarea
                    id="chat-input"
                    bind:this={composerElement}
                    bind:value={appState.chat.composerText}
                    placeholder={t('chat_placeholder', 'Type your message...')}
                    rows="3"
                    aria-keyshortcuts="Alt+Shift+I"
                    onkeydown={handleKeydown}
                    onfocus={focusChatComposer}
                    disabled={chatDisabled}
                ></textarea>
            </label>

            <div class="composer-toolbar">
                <button id="attach-files" type="button" aria-keyshortcuts="Alt+Shift+A" onclick={() => fileInputElement?.click()} disabled={chatDisabled}>{t('attach_button', 'Upload image')}</button>
            </div>

            <button id="chat-send" type="button" aria-keyshortcuts="Enter,Alt+Shift+S" onclick={() => submitChatMessage(fileInputElement)} disabled={chatDisabled}>{t('send_button', 'Send')}</button>
        </div>
    </section>
{/if}
