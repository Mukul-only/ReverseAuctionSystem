import { useNavigate } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { Eyebrow } from '../components/ui/Eyebrow'

export function NotFound() {
  const navigate = useNavigate()

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-24">
      <Eyebrow>404</Eyebrow>
      <h1 className="mt-3 text-heading-lg text-ink">
        This route does not exist.
      </h1>
      <p className="mt-2 text-body-md text-body">
        Check the URL or return to the auction floor.
      </p>
      <Button
        variant="primary-sm"
        className="mt-6"
        onClick={() => navigate('/')}
      >
        Go home
      </Button>
    </section>
  )
}