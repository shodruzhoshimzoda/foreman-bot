import { memo } from 'react'
import { avatarHue, initials } from '../format.js'

export default memo(function Avatar({ id, name, size = 36 }) {
  return (
    <span className="avatar" style={{ '--h': avatarHue(id), width: size, height: size, fontSize: size * 0.38 }} aria-hidden="true">
      {initials(name)}
    </span>
  )
})
