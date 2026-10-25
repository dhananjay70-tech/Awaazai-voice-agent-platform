/** A titled section of the studio's configuration workspace. */
export default function ConfigPanel({ title, description, actions, children, id }) {
  const headingId = id ? `${id}-title` : undefined
  return (
    <section className="config-panel" aria-labelledby={headingId} id={id}>
      <header className="config-panel-head">
        <div>
          <h3 id={headingId}>{title}</h3>
          {description && <p>{description}</p>}
        </div>
        {actions && <div className="config-panel-actions">{actions}</div>}
      </header>
      <div className="config-panel-body">{children}</div>
    </section>
  )
}
