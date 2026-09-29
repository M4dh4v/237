// Barrel for design-system primitives (contract §3 import path '@/design-system').
// tokens.css/scale.css/fonts.css are imported globally in main.jsx; primitives
// pull their own primitives.css. Lane B imports these, never edits them.
export { Button, Panel, Chip, Banner, Hash } from './primitives.jsx'
