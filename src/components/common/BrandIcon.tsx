import darkIcon from '../../../resources/icon.svg'
import lightIcon from '../../../resources/icon-light.svg'

/** Follow the app's existing theme without a second theme store. */
export function BrandIcon({ className }: { className: string }) {
  return (
    <span className={`merak-brand-icon ${className}`} aria-hidden="true">
      <img src={darkIcon} alt="" className="merak-brand-dark h-full w-full" />
      <img src={lightIcon} alt="" className="merak-brand-light h-full w-full" />
    </span>
  )
}
