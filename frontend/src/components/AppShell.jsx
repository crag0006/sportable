import { Link } from 'react-router-dom'
import Brand from './Brand'
import { ArrowLeftIcon } from './Icons'

export default function AppShell({
  backTo,
  backLabel,
  headline,
  sidebarChildren,
  children,
}) {
  return (
    <div className="app-layout">
      <aside className="app-sidebar">
        <div className="app-sidebar-inner">
          <Brand />

          <Link className="context-link" to={backTo}>
            <ArrowLeftIcon />
            <span>{backLabel}</span>
          </Link>

          <div className="headline-block">
            <h1>{headline}</h1>
          </div>

          {sidebarChildren}
        </div>
      </aside>

      <main className="app-content">
        <div className="content-inner">{children}</div>
      </main>
    </div>
  )
}
