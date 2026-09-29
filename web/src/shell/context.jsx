import { createContext, useCallback, useContext, useMemo, useState } from 'react'

/**
 * Role + lite-mode shell state (contract §4).
 *
 * Role is a frictionless UI select for the demo — NOT the security model. The
 * god-mode toggle lets one screen drive all three roles so the judges can watch
 * seal -> arrive -> trace without three logins; every surface that shows it must
 * label it "demo convenience — a real deployment separates these by credential."
 *
 * Lite mode is the manual escape hatch from 3D (joins prefers-reduced-motion):
 * when on, scenes render their static poster. It lives here so the StatusStrip
 * toggle and every scene read the same value.
 */

const RoleContext = createContext(null)
const LiteContext = createContext(null)

export function ShellProvider({ children }) {
  const [role, setRole] = useState(null) // 'sender' | 'recipient' | 'investigator' | null
  const [godMode, setGodMode] = useState(false)

  // prefers-reduced-motion is the OS-level opt-out; lite mode is the manual one.
  // Either being true means "show the poster". Seed from the media query once.
  const prefersReduced =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const [lite, setLite] = useState(Boolean(prefersReduced))

  const roleValue = useMemo(
    () => ({ role, setRole, godMode, setGodMode }),
    [role, godMode],
  )
  const toggleLite = useCallback(() => setLite((v) => !v), [])
  const liteValue = useMemo(() => ({ lite, toggleLite }), [lite, toggleLite])

  return (
    <RoleContext.Provider value={roleValue}>
      <LiteContext.Provider value={liteValue}>{children}</LiteContext.Provider>
    </RoleContext.Provider>
  )
}

export function useRole() {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRole must be used inside <ShellProvider>')
  return ctx
}

export function useLite() {
  const ctx = useContext(LiteContext)
  if (!ctx) throw new Error('useLite must be used inside <ShellProvider>')
  return ctx
}
