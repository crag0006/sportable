import { FacilityIconGlyph } from "./Icons";

function FacilityCard({ facility }) {
  // "state" decides the colour: green = good news, red = bad news,
  // grey = nothing published. 
  const state = facility.state || "unknown";

  return (
    <article className={`facility-card facility-${state}`}>
      <div className="facility-icon">
        <FacilityIconGlyph icon={facility.icon} />
      </div>

      <div className="facility-body">
        <div className="facility-top">
          <div>
            <h3>{facility.title}</h3>
            <p>{facility.description}</p>
          </div>

          <div className={`distance-pill distance-pill--${state}`}>
            {facility.pillText || facility.distance || "—"}
          </div>
        </div>
      </div>
    </article>
  );
}

export default FacilityCard;