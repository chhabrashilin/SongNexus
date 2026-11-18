/**
 * Bottom sheet and dialog on the native <dialog> element: focus is trapped,
 * Escape closes, and the page behind is inert, all without custom code.
 */
import {useEffect, useId, useRef, type ReactNode} from 'react';

import {useI18n} from '../i18n/i18n';

import {Icon} from './Icon';

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  variant?: 'sheet' | 'dialog';
  actions?: ReactNode;
}

export function Sheet({
  open,
  title,
  onClose,
  children,
  variant = 'sheet',
  actions,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const {t} = useI18n();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={variant}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={event => {
        // A click on the backdrop lands on the dialog element itself.
        if (event.target === ref.current) onClose();
      }}
    >
      {variant === 'sheet' && (
        <div className="sheet__handle" aria-hidden="true" />
      )}
      <div className="section__header">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="icon-btn" onClick={onClose}>
          <Icon name="close" label={t('action.close')} />
        </button>
      </div>
      <div className="stack" style={{marginBlockStart: 'var(--space-3)'}}>
        {open && children}
      </div>
      {actions && <div className="dialog__actions">{actions}</div>}
    </dialog>
  );
}
