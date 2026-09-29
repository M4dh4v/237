// Barrel for the shared honesty layer + WitnessRing (contract §3).
// Lane B imports from '@/components'; it never reaches into individual files,
// and never edits these — Lane A owns them.
export { default as StatusStrip } from './StatusStrip.jsx'
export { default as PresentNotVerified } from './PresentNotVerified.jsx'
export { default as FailClosed } from './FailClosed.jsx'
export { default as Caveat } from './Caveat.jsx'
export { default as ClassificationBanner } from './ClassificationBanner.jsx'
export { default as WitnessRing } from './WitnessRing.jsx'
export { default as SceneFallback } from './SceneFallback.jsx'
