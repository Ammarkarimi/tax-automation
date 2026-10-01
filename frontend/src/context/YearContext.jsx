import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../api/client'

const YearContext = createContext(null)

/** Selected tax year + static metadata (supported years, categories). */
export function YearProvider({ children }) {
  const [meta, setMeta] = useState({ supported_years: [], categories: [] })
  const [year, setYear] = useState(() => {
    try {
      return Number(sessionStorage.getItem('taxYear')) || null
    } catch {
      return null
    }
  })

  useEffect(() => {
    api.get('/meta').then((m) => {
      setMeta(m)
      setYear((current) => {
        if (current && m.supported_years.includes(current)) return current
        // Default to last year's return until the October extension deadline.
        const today = new Date(m.today)
        const filing = today.getMonth() < 9 || (today.getMonth() === 9 && today.getDate() <= 15)
        const guess = filing ? today.getFullYear() - 1 : today.getFullYear()
        return m.supported_years.includes(guess) ? guess : m.supported_years.at(-1)
      })
    })
  }, [])

  useEffect(() => {
    if (year) {
      try {
        sessionStorage.setItem('taxYear', String(year))
      } catch {
        /* storage unavailable */
      }
    }
  }, [year])

  return <YearContext.Provider value={{ year, setYear, meta }}>{children}</YearContext.Provider>
}

export const useYear = () => useContext(YearContext)
