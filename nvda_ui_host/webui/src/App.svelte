<script lang="ts">
    import { onMount } from 'svelte';
    import AccessibilityAnnouncer from './components/AccessibilityAnnouncer.svelte';
    import ChatComposer from './components/ChatComposer.svelte';
    import ChatPanel from './components/ChatPanel.svelte';
    import ControlPanel from './components/ControlPanel.svelte';
    import DisplayCard from './components/DisplayCard.svelte';
    import GlobalToolbar from './components/GlobalToolbar.svelte';
    import StatusCard from './components/StatusCard.svelte';
    import {
        clearDisplayedContent,
        copyCurrentMarkdown,
        copyCurrentText,
        focusChatComposer,
        focusContentRegion,
        focusModelSelect,
        focusProviderSelect,
        requestCloseHost,
        submitChatMessage,
    } from './lib/actions';
    import { initializeWebViewBridge } from './lib/bridge';
    import { registerGlobalShortcuts } from './lib/shortcuts';
    import { appState, t } from './lib/state.svelte';

    let statusElement: HTMLElement | null = $state(null);
    let contentElement: HTMLElement | null = $state(null);
    let composerElement: HTMLElement | null = $state(null);
    let firstResultActionElement: HTMLElement | null = $state(null);
    let fileInputElement: HTMLInputElement | null = $state(null);

    function focusElement(element: HTMLElement | null) {
        if (!element) return;
        window.requestAnimationFrame(() => {
            element.focus({ preventScroll: false });
        });
    }

    onMount(() => {
        initializeWebViewBridge();
        const cleanupShortcuts = registerGlobalShortcuts(
            {
                onClose: requestCloseHost,
                onCopyText: copyCurrentText,
                onCopyMarkdown: copyCurrentMarkdown,
                onClear: clearDisplayedContent,
                onFocusContent: focusContentRegion,
                onFocusComposer: focusChatComposer,
                onFocusProvider: focusProviderSelect,
                onFocusModel: focusModelSelect,
                onAttachFile: () => fileInputElement?.click(),
                onSubmit: submitChatMessage,
            },
            fileInputElement,
        );
        return cleanupShortcuts;
    });

    $effect(() => {
        const count = appState.chat.transcript.count;
        if (count >= 0 && appState.view.mode === 'chat' && contentElement instanceof HTMLElement) {
            const nearBottom = contentElement.scrollHeight - contentElement.scrollTop - contentElement.clientHeight < 80;
            if (!nearBottom && contentElement.scrollTop > 0) return;
            contentElement.scrollTop = contentElement.scrollHeight;
        }
    });

    $effect(() => {
        const target = appState.view.pendingFocus;
        if (!target) return;

        let element: HTMLElement | null = null;

        if (target === 'status') {
            element = statusElement;
        } else if (target === 'composer' && appState.view.mode === 'chat') {
            element = composerElement;
        } else if (target === 'primary_action') {
            element = firstResultActionElement;
        } else if (target === 'content') {
            element = contentElement;
        }

        if (!element) return;

        focusElement(element);
        appState.view.pendingFocus = null;
    });
</script>

<svelte:window />

<AccessibilityAnnouncer />

<div class="app-shell">
    <header class="app-header">
        <div class="title-block">
            <p class="eyebrow">{t('app_brand', 'NVDA AI Assistant')}</p>
            <h1 class="app-title">{t('app_title', 'Response Workspace')}</h1>
        </div>

        {#if appState.controlsVisible}
            <ControlPanel />
        {/if}
    </header>

    <main class="workspace">
        <StatusCard registerStatus={(element) => statusElement = element} />
        {#if appState.view.mode === 'chat'}
            <ChatPanel />
        {/if}

        <DisplayCard
            registerContent={(element) => contentElement = element}
            registerFirstAction={(element) => firstResultActionElement = element}
        />

        {#if appState.view.mode === 'chat'}
            <ChatComposer
                registerComposer={(element) => composerElement = element}
                registerFileInput={(element) => fileInputElement = element}
            />
        {/if}
    </main>

    <GlobalToolbar />
</div>
