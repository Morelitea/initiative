import { useEffect, useState } from "react";

export type ChesterMood =
  | "idle"
  | "talking"
  | "excited"
  | "farewell"
  | "thinking"
  | "proud"
  | "winking";

interface ChesterMimicProps {
  mood?: ChesterMood;
  size?: number;
}

/**
 * Chester the Mimic — a pixel-art treasure chest mascot.
 * Uses explicit colors for a retro look that works on any theme.
 *
 * Moods:
 *  - idle:     gentle bounce, eyes forward, mouth closed
 *  - talking:  mouth open with tongue, gentle bounce
 *  - excited:  lid chomps open/closed rapidly, fast bounce
 *  - farewell: mouth open, rocking wave
 *  - thinking: eyes look upward, slight tilt, mouth closed
 *  - proud:    happy squint eyes (^ ^), sparkle, mouth closed
 *  - winking:  one eye winks, slight tilt, mouth closed
 */
export const ChesterMimic = ({ mood = "idle", size = 80 }: ChesterMimicProps) => {
  const [blinking, setBlinking] = useState(false);

  useEffect(() => {
    // No random blinks for moods with special eye expressions
    if (mood === "proud" || mood === "winking") return;
    const blink = () => {
      setBlinking(true);
      setTimeout(() => setBlinking(false), 150);
    };
    const interval = setInterval(blink, 3000 + Math.random() * 2000);
    return () => clearInterval(interval);
  }, [mood]);

  const mouthOpen = mood === "talking" || mood === "excited" || mood === "farewell";
  const isChomping = mood === "excited";
  const eyeScaleY = blinking ? 0.15 : 1;

  const bounceClass =
    mood === "excited"
      ? "animate-chester-bounce-fast"
      : mood === "farewell"
        ? "animate-chester-wave"
        : mood === "thinking"
          ? "animate-chester-tilt"
          : mood === "winking"
            ? "animate-chester-tilt"
            : "animate-chester-bounce";

  // Pixel-art color palette
  const wood = "#8B5E3C";
  const woodLight = "#A97B50";
  const woodDark = "#5C3A1E";
  const metal = "#C9A84C";
  const metalDark = "#9E7B2F";
  const metalLight = "#E8D48B";
  const outline = "#2A1A0A";
  const eyeWhite = "#FFFDE8";
  const pupil = "#1A0A00";
  const tongue = "#D45B5B";
  const toothColor = "#FFFDE8";
  const interior = "#3A1F0F";
  const sparkle = "#FFE066";

  /** Render eyes based on mood */
  const renderEyes = () => {
    // Proud: happy squint eyes (^ ^)
    if (mood === "proud") {
      return (
        <g>
          <path
            d="M8 12.5 Q11 8 14 12.5"
            fill="none"
            stroke={outline}
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          <path
            d="M18 12.5 Q21 8 24 12.5"
            fill="none"
            stroke={outline}
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </g>
      );
    }

    // Winking: left eye normal, right eye is a happy curve
    if (mood === "winking") {
      return (
        <g>
          {/* Left eye — normal */}
          <ellipse
            cx="11"
            cy="11"
            rx="3"
            ry={3 * eyeScaleY}
            fill={eyeWhite}
            stroke={outline}
            strokeWidth="0.8"
            style={{ transition: "ry 0.1s ease" }}
          />
          {!blinking && (
            <>
              <circle cx="11.5" cy="11.5" r="1.5" fill={pupil} />
              <rect x="12" y="10" width="1" height="1" fill={eyeWhite} />
            </>
          )}
          {/* Right eye — wink (happy arc) */}
          <path
            d="M18 12 Q21 8.5 24 12"
            fill="none"
            stroke={outline}
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </g>
      );
    }

    // Thinking: eyes look upward and to the left
    if (mood === "thinking") {
      return (
        <g>
          <ellipse
            cx="11"
            cy="11"
            rx="3"
            ry={3 * eyeScaleY}
            fill={eyeWhite}
            stroke={outline}
            strokeWidth="0.8"
            style={{ transition: "ry 0.1s ease" }}
          />
          <ellipse
            cx="21"
            cy="11"
            rx="3"
            ry={3 * eyeScaleY}
            fill={eyeWhite}
            stroke={outline}
            strokeWidth="0.8"
            style={{ transition: "ry 0.1s ease" }}
          />
          {!blinking && (
            <>
              {/* Pupils shifted up-left */}
              <circle cx="10" cy="10" r="1.5" fill={pupil} />
              <circle cx="20" cy="10" r="1.5" fill={pupil} />
              <rect x="10.5" y="9" width="1" height="1" fill={eyeWhite} />
              <rect x="20.5" y="9" width="1" height="1" fill={eyeWhite} />
            </>
          )}
        </g>
      );
    }

    // Default eyes (idle, talking, excited, farewell)
    return (
      <g>
        <ellipse
          cx="11"
          cy="11"
          rx="3"
          ry={3 * eyeScaleY}
          fill={eyeWhite}
          stroke={outline}
          strokeWidth="0.8"
          style={{ transition: "ry 0.1s ease" }}
        />
        <ellipse
          cx="21"
          cy="11"
          rx="3"
          ry={3 * eyeScaleY}
          fill={eyeWhite}
          stroke={outline}
          strokeWidth="0.8"
          style={{ transition: "ry 0.1s ease" }}
        />
        {!blinking && (
          <>
            <circle cx="11.5" cy="11.5" r="1.5" fill={pupil} />
            <circle cx="21.5" cy="11.5" r="1.5" fill={pupil} />
            <rect x="12" y="10" width="1" height="1" fill={eyeWhite} />
            <rect x="22" y="10" width="1" height="1" fill={eyeWhite} />
          </>
        )}
      </g>
    );
  };

  return (
    <div className={bounceClass} style={{ width: size, height: size }}>
      <svg
        viewBox="0 0 32 32"
        width={size}
        height={size}
        aria-hidden="true"
        style={{ imageRendering: "pixelated" }}
      >
        {/* === CHEST BODY === */}
        <rect x="3" y="16" width="26" height="12" fill={wood} />
        <rect x="2" y="16" width="1" height="12" fill={outline} />
        <rect x="29" y="16" width="1" height="12" fill={outline} />
        <rect x="3" y="28" width="26" height="1" fill={outline} />
        <rect x="3" y="16" width="2" height="12" fill={woodLight} />
        <rect x="27" y="16" width="2" height="12" fill={woodDark} />
        <rect x="5" y="19" width="22" height="1" fill={woodDark} opacity="0.4" />
        <rect x="5" y="24" width="22" height="1" fill={woodDark} opacity="0.4" />

        {/* Metal band across body */}
        <rect x="2" y="21" width="28" height="3" fill={metal} />
        <rect x="2" y="21" width="28" height="1" fill={metalLight} />
        <rect x="2" y="23" width="28" height="1" fill={metalDark} />

        {/* Lock/clasp on body */}
        <rect
          x="13"
          y="19"
          width="6"
          height="6"
          rx="1"
          fill={metal}
          stroke={outline}
          strokeWidth="0.5"
        />
        <rect x="13" y="19" width="6" height="2" fill={metalLight} />
        <rect x="15" y="22" width="2" height="2" rx="1" fill={metalDark} />

        {/* Feet/corners */}
        <rect x="3" y="28" width="3" height="2" fill={metalDark} />
        <rect x="26" y="28" width="3" height="2" fill={metalDark} />

        {/* === MOUTH INTERIOR (visible when open) === */}
        {mouthOpen && <rect x="4" y="12" width="24" height="6" fill={interior} />}

        {/* === LID === */}
        <g
          className={isChomping ? "animate-chester-chomp" : undefined}
          style={{
            transformOrigin: "16px 14px",
            ...(isChomping
              ? {}
              : {
                  transition: "transform 0.2s ease",
                  transform: mouthOpen ? "rotate(-20deg)" : "rotate(0deg)",
                }),
          }}
        >
          <rect x="3" y="7" width="26" height="9" rx="2" fill={wood} />
          <rect x="2" y="7" width="1" height="9" fill={outline} />
          <rect x="29" y="7" width="1" height="9" fill={outline} />
          <rect x="3" y="6" width="26" height="1" fill={outline} />
          <rect x="3" y="7" width="26" height="2" fill={woodLight} />
          <rect x="3" y="14" width="26" height="2" fill={woodDark} />
          <rect x="2" y="10" width="28" height="3" fill={metal} />
          <rect x="2" y="10" width="28" height="1" fill={metalLight} />
          <rect x="2" y="12" width="28" height="1" fill={metalDark} />
          <circle cx="5" cy="11" r="1" fill={metalLight} />
          <circle cx="27" cy="11" r="1" fill={metalLight} />
        </g>

        {/* === EYES === */}
        {renderEyes()}

        {/* === SPARKLES (proud mood) === */}
        {mood === "proud" && (
          <g className="animate-chester-sparkle">
            <polygon
              points="27,5 27.8,7 30,7 28.2,8.2 28.8,10.5 27,9 25.2,10.5 25.8,8.2 24,7 26.2,7"
              fill={sparkle}
            />
            <polygon
              points="5,4 5.5,5.2 7,5.2 5.8,6 6.2,7.5 5,6.5 3.8,7.5 4.2,6 3,5.2 4.5,5.2"
              fill={sparkle}
              opacity="0.7"
            />
          </g>
        )}

        {/* === TEETH (when mouth is open) === */}
        {mouthOpen && (
          <g>
            {[6, 9, 12, 15, 18, 21, 24].map((x) => (
              <polygon
                key={`u-${x}`}
                points={`${x},16 ${x + 2},16 ${x + 1},19`}
                fill={toothColor}
                stroke={outline}
                strokeWidth="0.3"
              />
            ))}
            {[7, 10, 13, 16, 19, 22].map((x) => (
              <polygon
                key={`l-${x}`}
                points={`${x},18 ${x + 2},18 ${x + 1},15.5`}
                fill={toothColor}
                stroke={outline}
                strokeWidth="0.3"
              />
            ))}
          </g>
        )}

        {/* Tongue — wide, forked, snake-like with shadow */}
        {mouthOpen && (
          <g className="animate-chester-tongue">
            <path
              d="M16 17 Q14.5 20.5 13.5 23.5 Q13 25 12.5 25.5"
              fill="none"
              stroke="#1A0A0A"
              strokeWidth="3.5"
              strokeLinecap="round"
              opacity="0.3"
            />
            <path
              d="M12.5 25.5 L10.5 27.5"
              fill="none"
              stroke="#1A0A0A"
              strokeWidth="2"
              strokeLinecap="round"
              opacity="0.3"
            />
            <path
              d="M12.5 25.5 L13 27.5"
              fill="none"
              stroke="#1A0A0A"
              strokeWidth="2"
              strokeLinecap="round"
              opacity="0.3"
            />
            <path
              d="M16 17 Q14.5 20.5 13.5 23.5 Q13 25 12.5 25.5"
              fill="none"
              stroke={tongue}
              strokeWidth="2.5"
              strokeLinecap="round"
            />
            <path
              d="M12.5 25.5 L10.5 27.5"
              fill="none"
              stroke={tongue}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
            <path
              d="M12.5 25.5 L13 27.5"
              fill="none"
              stroke={tongue}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </g>
        )}
      </svg>
    </div>
  );
};
