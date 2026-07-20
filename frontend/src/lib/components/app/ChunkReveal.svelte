<!--
  Blueprint #1 — The Fluid Stream Reveal, on Svelte's built-in svelte/motion.
  Each streamed chunk mounts invisible, blurred and slightly dropped, then its Tween
  eases it to full presence (ease-out). Because every chunk animates on entry, the
  answer flows in organically instead of snapping block-by-block. A Tween (time-based)
  is used here rather than a Spring because it's light enough to run one per chunk.
-->
<script lang="ts">
	import { Tween, prefersReducedMotion } from 'svelte/motion';

	let { text }: { text: string } = $props();

	const reveal = new Tween(0, {
		duration: prefersReducedMotion.current ? 1 : 340,
		easing: (t) => 1 - Math.pow(1 - t, 3) // easeOutCubic
	});

	// Kick the tween once mounted so it always animates 0 → 1.
	$effect(() => {
		reveal.set(1);
	});
</script>

<span
	class="inline will-change-transform"
	style:opacity={reveal.current}
	style:filter={`blur(${(1 - reveal.current) * 4}px)`}
	style:translate={`0 ${(1 - reveal.current) * 6}px`}
>{text}</span>
