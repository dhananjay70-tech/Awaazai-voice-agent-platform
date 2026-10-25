import Alert from './Alert.jsx'
import Button from './Button.jsx'

/** The standard honest banner for a feature that has no backend yet. */
export function ComingSoonNotice({ title = 'Coming soon', children }) {
  return (
    <Alert tone="warning" title={title}>
      {children}
    </Alert>
  )
}

/** A control that will exist later: visibly disabled, labelled, and never pretending to work. */
export function ComingSoonButton({ icon, children, ...rest }) {
  return (
    <Button icon={icon} disabled title="Coming soon" {...rest}>
      {children}
      <span className="badge badge-warning" style={{ marginLeft: 4 }}>
        Soon
      </span>
    </Button>
  )
}
