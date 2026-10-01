export default function Protein() {
  const pts = Array.from({ length: 75 }, (_, i) => {
    const t = i * 0.25;
    return [
      260 + Math.sin(t) * 86 + Math.sin(t * 0.31) * 94,
      35 + i * 5.7 + Math.cos(t * 0.31) * 26,
      Math.cos(t),
    ].map((value) => Number(value.toFixed(3)));
  });
  return (
    <svg
      className="protein"
      viewBox="0 0 600 550"
      role="img"
      aria-label="단백질 3차원 구조의 추상적 시각화"
    >
      <defs>
        <linearGradient id="strand" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#beadff" />
          <stop offset=".5" stopColor="#6c65da" />
          <stop offset="1" stopColor="#363170" />
        </linearGradient>
        <linearGradient id="strand2">
          <stop stopColor="#e1d6ff" />
          <stop offset="1" stopColor="#8479b9" />
        </linearGradient>
        <filter id="shadow">
          <feDropShadow
            dx="2"
            dy="6"
            stdDeviation="6"
            floodColor="#6e5d9d"
            floodOpacity=".22"
          />
        </filter>
      </defs>
      <g className="orbit">
        <ellipse
          cx="310"
          cy="265"
          rx="230"
          ry="145"
          fill="none"
          stroke="#d9d5ea"
          strokeDasharray="3 7"
          transform="rotate(-35 310 265)"
        />
        <ellipse
          cx="310"
          cy="265"
          rx="196"
          ry="185"
          fill="none"
          stroke="#e2dfed"
          transform="rotate(30 310 265)"
        />
      </g>
      <g transform="rotate(-24 300 270)" filter="url(#shadow)">
        {pts.slice(0, -1).map((p, i) => {
          const q = pts[i + 1];
          return (
            <g key={i}>
              <path
                d={`M${p[0]} ${p[1]} Q${p[0] + 30} ${p[1] + 14} ${q[0]} ${q[1]}`}
                stroke="url(#strand)"
                strokeWidth={Number((12 + p[2] * 5).toFixed(3))}
                fill="none"
                strokeLinecap="round"
              />
              {i % 3 === 0 && (
                <path
                  d={`M${p[0]} ${p[1]} Q${p[0] + 48} ${p[1] - 7} ${p[0] + 72} ${p[1] + 24}`}
                  stroke="#b9acd6"
                  strokeWidth="2.3"
                  fill="none"
                />
              )}
            </g>
          );
        })}
        <path
          d="M226 92 C420 50 515 155 386 198 S155 155 212 284 S470 320 385 393 S166 478 167 335 S95 242 179 180"
          stroke="url(#strand2)"
          strokeWidth="12"
          fill="none"
          strokeLinecap="round"
        />
        <path
          d="M228 93 C420 50 515 155 386 198 S155 155 212 284 S470 320 385 393"
          stroke="#ede6fc"
          strokeWidth="2"
          fill="none"
        />
      </g>
      <g fill="#9584c9">
        {[
          [91, 176],
          [474, 109],
          [485, 384],
          [177, 466],
          [392, 463],
        ].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i === 1 ? 5 : 3} />
        ))}
      </g>
      <g className="svg-label">
        <rect
          x="364"
          y="61"
          width="148"
          height="35"
          rx="7"
          fill="white"
          stroke="#e6e2f0"
        />
        <text x="380" y="83">
          CATH · ARCHITECTURE
        </text>
        <path d="M394 96 L388 132" stroke="#b4a5d0" />
        <rect
          x="53"
          y="389"
          width="162"
          height="37"
          rx="7"
          fill="white"
          stroke="#e6e2f0"
        />
        <circle cx="70" cy="407" r="4" fill="#8a71cc" />
        <text x="82" y="411">
          3D COORDINATES
        </text>
      </g>
    </svg>
  );
}
