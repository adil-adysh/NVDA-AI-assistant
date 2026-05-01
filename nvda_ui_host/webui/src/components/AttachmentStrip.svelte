<script>
    import { removeAttachment } from '../lib/attachments.js';
    import { appState, t } from '../lib/state.svelte.js';
</script>

{#if appState.chat.attachments.length > 0}
    <div id="attachment-strip" class="attachment-strip" aria-label="Pending attachments">
        {#each appState.chat.attachments as attachment (attachment.id)}
            <div class="attachment-chip">
                <span>{attachment.name || attachment.kind || t('attachment_fallback_name', 'Attachment')}</span>
                <button type="button" onclick={() => removeAttachment(attachment.id)}>{t('remove_attachment', 'Remove')}</button>
            </div>
        {/each}
    </div>
{/if}
