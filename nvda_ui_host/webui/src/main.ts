import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';

const target = document.getElementById('app');

if (!target) {
	throw new Error('Unable to find WebView app root.');
}

mount(App, { target });
