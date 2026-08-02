<!--
  3D hero: a floating fan of Tamil Nadu textbooks (one per subject).
  The Canvas fills its positioned parent and is transparent (alpha) so the CSS
  ink-gradient behind it shows through. Threlte 8 passes WebGL parameters via the
  `createRenderer` factory (there is no `gl` prop); `dpr` clamps pixel ratio.
-->
<script lang="ts">
	import { Canvas } from '@threlte/core';
	import { WebGLRenderer } from 'three';
	import BookFan from './BookFan.svelte';
</script>

<div class="absolute inset-0 scale-[0.5] origin-[100%_40%] sm:scale-100 sm:origin-center transition-transform duration-500" aria-hidden="true">
	<Canvas
		dpr={[1, 1.75]}
		createRenderer={(canvas) =>
			new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' })}
	>
		<BookFan />
	</Canvas>
</div>
