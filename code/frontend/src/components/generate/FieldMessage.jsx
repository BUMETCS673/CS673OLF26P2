/** The hint under a field, or its error in place of the hint. */
export default function FieldMessage({ id, error, children }) {
  return <p id={id} className={error ? 'field-error' : 'field-hint'}>{error || children}</p>;
}
