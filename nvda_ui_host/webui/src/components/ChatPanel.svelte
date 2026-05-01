<script>
    import { handleFileSelection } from '../lib/attachments.js';
    import { focusChatComposer, submitChatMessage } from '../lib/actions.js';
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
</script>

{#if appState.view.mode === 'chat'}
    <section id="chat-panel" class="workspace-card chat-panel" aria-label={t('chat_heading', 'Chat')}>
        <input id="file-input" bind:this={fileInputElement} type="file" multiple hidden onchange={handleInputFiles} />

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
            ></textarea>
        </label>

        <div class="composer-toolbar">
            <button id="attach-files" type="button" aria-keyshortcuts="Alt+Shift+A" onclick={() => fileInputElement?.click()}>{t('attach_button', 'Attach')}</button>
        </div>

        <button id="chat-send" type="button" aria-keyshortcuts="Enter,Alt+Shift+S" onclick={() => submitChatMessage(fileInputElement)}>{t('send_button', 'Send')}</button>
    </section>
{/if}
