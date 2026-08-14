<script>
    import { invokeResultAction } from '../lib/actions';
    import { appState, t } from '../lib/state.svelte';
    import ContentBlock from './ContentBlock.svelte';

    let { registerContent = () => {}, registerFirstAction = () => {} } = $props();
    let contentElement = $state(null);
    let firstActionElement = $state(null);

    $effect(() => {
        registerContent(contentElement);
        return () => registerContent(null);
    });

    $effect(() => {
        registerFirstAction(firstActionElement);
        return () => registerFirstAction(null);
    });
</script>

<section class="workspace-card content-card one-shot-result-screen" aria-labelledby="result-heading">
    <div class="section-header">
        <h2 id="result-heading" class="section-title">{t('result_heading', 'Result')}</h2>
    </div>

    <div id="content" bind:this={contentElement} role="region" aria-live="off" tabindex="-1">
        {#each appState.display.blocks as block, index (`display-${index}`)}
            <ContentBlock {block} />
        {/each}

        {#if appState.display.actions.length > 0}
            <div class="result-actions" aria-label={t('result_actions_label', 'Result actions')}>
                <button
                    bind:this={firstActionElement}
                    type="button"
                    onclick={() => invokeResultAction(appState.display.actions[0])}
                >
                    {appState.display.actions[0].label || appState.display.actions[0].id || t('result_action_fallback_label', 'Action')}
                </button>

                {#each appState.display.actions.slice(1) as action, index (action.id || `action-${index + 1}`)}
                    <button
                        type="button"
                        onclick={() => invokeResultAction(action)}
                    >
                        {action.label || action.id || t('result_action_fallback_label', 'Action')}
                    </button>
                {/each}
            </div>
        {/if}
    </div>
</section>
