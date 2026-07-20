<!--
  The animated textbook fan. Must live INSIDE <Canvas> so useTask has a Threlte context.

  Motion model:
   - `input` is a plain mutable object updated by pointer/scroll listeners (always fresh,
     read every frame inside useTask — no reactivity needed for the inputs).
   - `rotX/rotY/t` are $state, mutated in useTask and bound to three.js props, so the
     scene re-renders each frame (the idiomatic Threlte 8 + Svelte 5 pattern).
-->
<script lang="ts">
	import { T, useTask } from '@threlte/core';

	// One book per subject — the palette doubles as the subject identity.
	const BOOKS = [
		{ color: '#ffb703', subject: 'Science' },
		{ color: '#ff6b4a', subject: 'Mathematics' },
		{ color: '#2ec4b6', subject: 'Social Science' },
		{ color: '#4cc9f0', subject: 'English' },
		{ color: '#b388eb', subject: 'Computer Applications' },
		{ color: '#8ac926', subject: 'History' }
	];

	// Ambient "knowledge motes" — deterministic positions, no Math.random at render.
	const MOTES = Array.from({ length: 14 }, (_, j) => ({
		x: Math.sin(j * 2.4) * 5.2,
		y: Math.cos(j * 1.7) * 2.6,
		z: Math.sin(j * 1.13) * 3 - 2.5,
		speed: 0.5 + (j % 5) * 0.18,
		phase: j * 0.9,
		color: j % 3 === 0 ? '#ffb703' : j % 3 === 1 ? '#2ec4b6' : '#4cc9f0',
		size: 0.035 + (j % 4) * 0.014
	}));

	const CENTER = (BOOKS.length - 1) / 2;
	const RADIUS = 4.4;

	// Fresh-every-frame inputs (mutated by listeners, read in useTask / template).
	const input = { px: 0, py: 0, spread: 1 };

	let rotY = $state(0);
	let rotX = $state(0);
	let t = $state(0);

	useTask((delta) => {
		t += delta;
		// Ease the whole fan toward the pointer for a parallax feel.
		rotY += (input.px * 0.38 - rotY) * 0.055;
		rotX += (input.py * 0.22 - rotX) * 0.055;
	});

	$effect(() => {
		const onMove = (e: PointerEvent) => {
			input.px = (e.clientX / window.innerWidth) * 2 - 1;
			input.py = (e.clientY / window.innerHeight) * 2 - 1;
		};
		const onScroll = () => {
			// Fan opens up as the visitor scrolls into the page.
			input.spread = 1 + Math.min(window.scrollY / 640, 1) * 0.85;
		};
		window.addEventListener('pointermove', onMove, { passive: true });
		window.addEventListener('scroll', onScroll, { passive: true });
		return () => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('scroll', onScroll);
		};
	});

	function bookTransform(i: number) {
		const rel = i - CENTER;
		const angle = rel * 0.4 * input.spread;
		return {
			x: Math.sin(angle) * RADIUS,
			z: Math.cos(angle) * RADIUS - RADIUS,
			ry: -angle * 0.85,
			rz: rel * 0.035,
			phase: i * 1.1,
			speed: 0.8 + (i % 3) * 0.22
		};
	}
</script>

<T.PerspectiveCamera makeDefault position={[0, 0.7, 10.6]} fov={40} />

<T.AmbientLight intensity={0.75} />
<T.DirectionalLight position={[4.5, 6, 5]} intensity={1.25} color="#fff7e6" />
<T.DirectionalLight position={[-6, -2, -4]} intensity={0.5} color="#2ec4b6" />

<T.Group rotation.y={rotY} rotation.x={rotX} position={[0.6, -0.15, 0]}>
	{#each BOOKS as book, i}
		{@const tr = bookTransform(i)}
		<T.Mesh
			position={[tr.x, Math.sin(t * tr.speed + tr.phase) * 0.17, tr.z]}
			rotation={[0, tr.ry, tr.rz]}
		>
			<T.BoxGeometry args={[2.05, 2.85, 0.34]} />
			<T.MeshStandardMaterial
				color={book.color}
				roughness={0.5}
				metalness={0.08}
				emissive={book.color}
				emissiveIntensity={0.14}
			/>
		</T.Mesh>
		<!-- Pale "page block" on the fore-edge sells the book silhouette -->
		<T.Mesh
			position={[tr.x + 1.0, Math.sin(t * tr.speed + tr.phase) * 0.17, tr.z]}
			rotation={[0, tr.ry, tr.rz]}
		>
			<T.BoxGeometry args={[0.06, 2.62, 0.26]} />
			<T.MeshStandardMaterial color="#f7f5f0" roughness={0.9} />
		</T.Mesh>
	{/each}
</T.Group>

<!-- Ambient motes -->
{#each MOTES as m}
	<T.Mesh position={[m.x, m.y + Math.sin(t * m.speed + m.phase) * 0.35, m.z]}>
		<T.SphereGeometry args={[m.size, 10, 10]} />
		<T.MeshBasicMaterial color={m.color} transparent opacity={0.65} />
	</T.Mesh>
{/each}
