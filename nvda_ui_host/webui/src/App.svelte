<script>
    import { onMount } from 'svelte';
    import {
        clearDisplayedContent,
        copyCurrentMarkdown,
        copyCurrentText,
        focusChatComposer,
        focusContentRegion,
        requestCloseHost,
        submitChatMessage,
    } from './lib/actions.js';
    import { initializeWebViewBridge } from './lib/bridge.js';
    import { appState, t } from './lib/state.svelte.js';
    import ChatPanel from './components/ChatPanel.svelte';
    import ControlPanel from './components/ControlPanel.svelte';
    import DisplayCard from './components/DisplayCard.svelte';
    import GlobalToolbar from './components/GlobalToolbar.svelte';
    import StatusCard from './components/StatusCard.svelte';

    let statusElement = $state(null);
    let contentElement = $state(null);
    let composerElement = $state(null);
    let firstResultActionElement = $state(null);
    let fileInputElement = $state(null);

    function isTextEntryTarget(target) {
        return target instanceof HTMLInputElement
            || target instanceof HTMLTextAreaElement
            || target instanceof HTMLSelectElement
            || target?.isContentEditable === true;
    }

    function focusElement(element) {
        if (!(element instanceof HTMLElement)) {
            return;
        }

        window.requestAnimationFrame(() => {
            element.focus({ preventScroll: false });
        });
    }

    function hasToolbarAction(actionId) {
        return Array.isArray(appState.display.toolbarActions) && appState.display.toolbarActions.includes(actionId);
    }

    function handleGlobalShortcut(event) {
        if (event.key === 'Escape') {
            if (event.repeat) {
                return;
            }
            event.preventDefault();
            requestCloseHost();
            return;
        }

        if (!(event.altKey && event.shiftKey) || event.repeat) {
            return;
        }

        const shortcut = event.key.toLowerCase();
        const activeTarget = document.activeElement;
        if (isTextEntryTarget(activeTarget) && shortcut !== 'i' && shortcut !== 's') {
            return;
        }

        switch (shortcut) {
            case 't':
                if (!hasToolbarAction('copy_text')) {
                    return;
                }
                event.preventDefault();
                copyCurrentText();
                break;
            case 'm':
                if (!hasToolbarAction('copy_markdown')) {
                    return;
                }
                event.preventDefault();
                copyCurrentMarkdown();
                break;
            case 'r':
                if (!hasToolbarAction('clear')) {
                    return;
                }
                event.preventDefault();
                clearDisplayedContent();
                break;
            case 'l':
                event.preventDefault();
                focusContentRegion();
                break;
            case 'i':
                if (appState.view.mode !== 'chat') {
                    return;
                }
                event.preventDefault();
                focusChatComposer();
                break;
            case 'a':
                if (appState.view.mode !== 'chat') {
                    return;
                }
                event.preventDefault();
                fileInputElement?.click();
                break;
            case 's':
                if (appState.view.mode !== 'chat') {
                    return;
                }
                event.preventDefault();
                submitChatMessage(fileInputElement);
                break;
            default:
                break;
        }
    }

    onMount(() => initializeWebViewBridge());

    $effect(() => {
        document.title = appState.title;
    });

    $effect(() => {
        const renderVersion = appState.chat.renderVersion;
        if (renderVersion >= 0 && appState.view.mode === 'chat' && contentElement instanceof HTMLElement) {
            const nearBottom = contentElement.scrollHeight - contentElement.scrollTop - contentElement.clientHeight < 80;
            if (!nearBottom && contentElement.scrollTop > 0) {
                return;
            }
            contentElement.scrollTop = contentElement.scrollHeight;
        }
    });

    $effect(() => {
        const target = appState.view.pendingFocus;

        if (!target) {
            return;
        }

        let element = null;

        if (target === 'status') {
            element = statusElement;
        } else if (target === 'composer' && appState.view.mode === 'chat') {
            element = composerElement;
        } else if (target === 'primary_action') {
            element = firstResultActionElement;
        } else if (target === 'content') {
            element = contentElement;
        }

        if (!element) {
            return;
        }

        focusElement(element);
        appState.view.pendingFocus = null;
    });
</script>

<svelte:window onkeydown={handleGlobalShortcut} />

<div id="announcer" class="sr-only" aria-live="assertive" aria-atomic="true">{appState.announcerMessage}</div>

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
        <DisplayCard
            registerContent={(element) => contentElement = element}
            registerFirstAction={(element) => firstResultActionElement = element}
        />
        <ChatPanel
            registerComposer={(element) => composerElement = element}
            registerFileInput={(element) => fileInputElement = element}
        />
    </main>

    <GlobalToolbar />
</div>
