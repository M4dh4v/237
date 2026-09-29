import { useEffect } from 'react'
import Lenis from 'lenis'

/**
 * Lenis smooth scroll for the landing route ONLY (sakshya-3d: dashboards never
 * run it). One instance, one RAF loop, torn down on unmount so a dashboard
 * mount is never left with a rogue scroll hijack. It writes a single 0→1
 * progress into `progressRef` on every scroll frame — the R3F scene reads that
 * ref inside useFrame (no React re-render per frame), and HTML station reveals
 * use Framer's own whileInView. One scroll value drives the whole journey.
 *
 * Honors reduced-motion / lite by simply not mounting (caller guards): the
 * posters then read as still frames with native scroll.
 */
export default function useLenisProgress(progressRef, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined
    const lenis = new Lenis({
      duration: 1.1,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
    })
    let raf
    const loop = (time) => {
      lenis.raf(time)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    const onScroll = () => {
      progressRef.current = lenis.limit > 0 ? lenis.scroll / lenis.limit : 0
    }
    lenis.on('scroll', onScroll)
    return () => {
      cancelAnimationFrame(raf)
      lenis.destroy()
    }
  }, [progressRef, enabled])
}
