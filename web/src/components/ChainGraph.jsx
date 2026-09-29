// The ledger, drawn by Cytoscape as a chain of leaves under one signed head.
//
// Ported from new237's ChainGraph, but the semantics are this system's, not
// that one's, and the difference matters enough to state. new237 drew a
// blockchain: each block carried its OWN quorum, so a node could be green while
// its neighbour was red. This is a Merkle transparency log. There is one signed
// tree head, and every committed leaf is included under it -- so "does this leaf
// carry quorum?" is not a per-leaf question here. The single judgement on the
// canvas is whether the CURRENT head is co-signed by at least the required
// number of witnesses, and that verdict colours every leaf the same, because
// every leaf shares that one head.
//
// As everywhere else in this app: the colour reports ARRIVAL, not a check. Green
// means "this many witness co-signatures were present on the head we received",
// not "the browser verified them" -- it cannot (see LedgerView's STANDING_NOTE).

import cytoscape from 'cytoscape'
import { useEffect, useRef } from 'react'

// Pulled from styles.css so the graph and the rest of the page cannot drift:
// --present, --absent, --accent, --bg-input, --line-strong, --fg, --fg-faint.
const PRESENT = '#6cc49a'
const ABSENT = '#e0796f'
const ACCENT = '#6aa6d8'
const NODE_BG = '#0d1116'
const EDGE = '#3a4653'
const FG = '#dfe6ee'

/**
 * @param {object} props
 * @param {Array} props.elements  Cytoscape element list; leaf nodes carry
 *   `data.index` and `data.tone` ('q' quorum / 'x' short), the head node
 *   carries `data.head = true`.
 * @param {(index:number|null)=>void} [props.onSelect]  index of a tapped leaf,
 *   or null when the head node is tapped.
 * @param {number} [props.selected]  index to highlight from outside the canvas.
 */
export function ChainGraph({ elements, onSelect, selected }) {
  const containerRef = useRef(null)
  const cyRef = useRef(null)

  useEffect(() => {
    if (containerRef.current === null) return undefined

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            color: FG,
            'font-family': 'ui-monospace, monospace',
            'font-size': 11,
            'text-valign': 'center',
            'text-halign': 'center',
            width: 36,
            height: 36,
            'background-color': NODE_BG,
            'border-width': 2,
            'border-color': EDGE,
          },
        },
        // The head is the STH itself, not a leaf: a diamond, tinted by the same
        // quorum verdict the leaves carry, since it is the head that carries it.
        {
          selector: 'node[head]',
          style: { shape: 'diamond', width: 46, height: 46, label: 'data(label)' },
        },
        {
          selector: 'node[tone = "q"]',
          style: { 'border-color': PRESENT, color: PRESENT },
        },
        {
          selector: 'node[tone = "x"]',
          style: { 'border-color': ABSENT, color: ABSENT },
        },
        {
          selector: 'node:selected',
          style: { 'background-color': ACCENT, color: NODE_BG, 'border-color': ACCENT },
        },
        {
          selector: 'edge',
          style: {
            width: 1,
            'line-color': EDGE,
            'target-arrow-color': EDGE,
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
          },
        },
      ],
      layout: { name: 'breadthfirst', directed: true, padding: 10 },
    })

    cy.on('tap', 'node', (event) => {
      const data = event.target.data()
      if (onSelect) onSelect(data.head ? null : data.index)
    })

    cyRef.current = cy
    return () => {
      cyRef.current = null
      cy.destroy()
    }
    // onSelect is intentionally omitted: rebuilding the graph because a parent
    // re-rendered would discard the reader's pan and zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements])

  // Reflect an outside selection without rebuilding the canvas.
  useEffect(() => {
    const cy = cyRef.current
    if (cy === null || selected === null || selected === undefined) return
    const match = elements.find((el) => el.data.index === selected)
    const node = cy.getElementById(match?.data.id ?? '')
    if (node.length > 0) {
      cy.elements().unselect()
      node.select()
    }
  }, [selected, elements])

  return (
    <div>
      <div
        ref={containerRef}
        className="chain-graph"
        role="img"
        aria-label="the ledger as a chain of leaves, each appended after the one before it, all included under a single witness-co-signed tree head"
      />
      <div className="chain-legend">
        <span className="chain-legend-item">
          <span className="chain-swatch chain-swatch-q" aria-hidden="true" />
          head co-signed by ≥ quorum witnesses (as received — not a check here)
        </span>
        <span className="chain-legend-item">
          <span className="chain-swatch chain-swatch-x" aria-hidden="true" />
          quorum not present on the head we received
        </span>
        <span>edge: appended after · diamond: the current signed tree head</span>
      </div>
    </div>
  )
}
