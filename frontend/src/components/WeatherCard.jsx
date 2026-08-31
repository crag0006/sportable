import { CloudIcon } from './Icons'

export default function WeatherCard({ data }) {
  return (
    <section className="mini-note-card">
      <span className="side-label">{'Weather'}</span>

      <div className="weather-card">
        <div className="weather-top">
          <div className="weather-main">
            <strong>{data.temperature}</strong>
            <span>{data.summary}</span>
          </div>

          <div className="weather-icon">
            <CloudIcon />
          </div>
        </div>

        <div className="weather-grid">
          {data.stats.map((item) => (
            <div key={item.label} className="weather-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>

        <div className="weather-tip">{data.tip}</div>
      </div>
    </section>
  )
}
