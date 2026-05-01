<script>
    import { removeAttachment } from '../lib/attachments.js';
    import { appState, t } from '../lib/state.svelte.js';
</script>

{#if appState.chat.attachments.length > 0}
    <div id="attachment-strip" class="attachment-strip" aria-label={t('pending_attachments_label', 'Pending attachments')}>
        {#each appState.chat.attachments as attachment (attachment.id)}
            <div class="attachment-chip">
                {#if attachment.kind === 'image' && attachment.image_base64}
                    <img
                        class="attachment-preview"
                        src={`data:${attachment.mime_type || 'image/png'};base64,${attachment.image_base64}`}
                        alt={attachment.name || t('attachment_fallback_name', 'Attachment')}
                        loading="lazy"
                    />
                {/if}
                <span>{attachment.name || attachment.kind || t('attachment_fallback_name', 'Attachment')}</span>
                <button type="button" onclick={() => removeAttachment(attachment.id)}>{t('remove_attachment', 'Remove')}</button>
            </div>
        {/each}
    </div>
{/if}
