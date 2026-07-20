// Theme store using Svelte 5 reactive $state
export type Theme = 'dark' | 'light';

class ThemeStore {
	current = $state<Theme>('dark');

	toggle() {
		this.set(this.current === 'dark' ? 'light' : 'dark');
	}

	set(theme: Theme) {
		this.current = theme;
		if (typeof document !== 'undefined') {
			document.documentElement.classList.toggle('dark', theme === 'dark');
		}
	}
}

export const themeState = new ThemeStore();

