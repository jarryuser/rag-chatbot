import { useEffect, useRef } from 'react'

export default function ReplacementDialog({ replacement, onConfirm, onCancel }) {
  const dialog = useRef(null)
  useEffect(() => {
    if (replacement) dialog.current?.showModal()
    else dialog.current?.close()
  }, [replacement])
  return (
    <dialog ref={dialog} className="replacement-dialog" aria-labelledby="replacement-title"
      onCancel={event => { event.preventDefault(); onCancel() }}>
      <h2 id="replacement-title">Replace document?</h2>
      <p>A different version of <strong>{replacement?.source}</strong> is already indexed in this chat.</p>
      <p>Replace it with the new content? Existing answers keep their original source passages.</p>
      <div className="replacement-actions">
        <button onClick={onCancel}>Keep existing</button>
        <button onClick={onConfirm}>Replace document</button>
      </div>
    </dialog>
  )
}
