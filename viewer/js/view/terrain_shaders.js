// The terrain's GPU programs: the aerial photo or relief, the signal shadow, the range circles and the corridor.
// terrainFS(maxLinks) because the number of radio links is part of the program.

export const terrainVS = /* glsl */`
  #include <common>
  #include <logdepthbuf_pars_vertex>
  attribute float aH;
  varying vec2 vUv; varying vec3 vNormal; varying vec3 vReal; varying float vH;
  uniform vec2 uSize;
  void main() {
    vUv = uv; vNormal = normalize(normal); vH = aH;
    vReal = vec3(position.x, aH, position.z);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    #include <logdepthbuf_vertex>
  }`;
export const terrainFS = (maxLinks) => /* glsl */`
  #include <logdepthbuf_pars_fragment>
  uniform sampler2D uOrtho; uniform sampler2D uLos; uniform sampler2D uZones; uniform float uZonesOn;
  uniform float uUseOrtho, uLosOn, uLosOpacity, uHMin, uHMax;
  uniform vec4 uOrthoRect; uniform vec4 uHole;
  uniform vec2 uCor[64]; uniform int uCorN; uniform float uCorW;   // route corridor (world x/z)
  float corDist(vec2 p) {
    float d = 1e9;
    for (int i = 0; i < 63; i++) {
      if (i >= uCorN - 1) break;
      vec2 a = uCor[i], ab = uCor[i + 1] - a;
      float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-6), 0.0, 1.0);
      d = min(d, length(p - (a + t * ab)));
    }
    return d;
  }
  uniform vec3 uPilot; uniform vec4 uRanges; uniform vec3 uColors[${maxLinks}]; uniform vec4 uRangeOn;
  varying vec2 vUv; varying vec3 vNormal; varying vec3 vReal; varying float vH;
  vec3 hypso(float t) {
    vec3 a = vec3(0.36,0.52,0.30), b = vec3(0.62,0.66,0.45), c = vec3(0.62,0.55,0.46), d = vec3(0.95,0.95,0.97);
    return t < .4 ? mix(a,b,t/.4) : t < .8 ? mix(b,c,(t-.4)/.4) : mix(c,d,(t-.8)/.2);
  }
  void main() {
    #include <logdepthbuf_fragment>
    if (vReal.x > uHole.x && vReal.x < uHole.z && vReal.z > uHole.y && vReal.z < uHole.w) discard;  // sharp close-up drawn there
    float cd = uCorN > 1 ? corDist(vReal.xz) : -1.0;
    if (cd > uCorW) discard;                      // outside the route strip
    vec3 sun = normalize(vec3(-0.5, 0.8, 0.35));
    float ndl = max(dot(normalize(vNormal), sun), 0.0);
    vec3 col = uUseOrtho > 0.5 ? texture2D(uOrtho, (vUv - uOrthoRect.xy) / (uOrthoRect.zw - uOrthoRect.xy)).rgb : hypso(clamp(vH / max(uHMax - uHMin, 1.0), 0.0, 1.0));
    col *= (uUseOrtho > 0.5 ? 0.75 + 0.45 * ndl : 0.45 + 0.75 * ndl);
    if (uLosOn > 0.5) { vec4 l = texture2D(uLos, vUv); col = mix(col, l.rgb, l.a * uLosOpacity); }
    if (uZonesOn > 0.5) {                       // drone geozones: diagonal hatching
      vec4 z = texture2D(uZones, vUv);
      float hatch = 0.45 + 0.55 * step(0.5, fract((gl_FragCoord.x - gl_FragCoord.y) / 14.0));
      col = mix(col, z.rgb, z.a * hatch);
    }
    float d = distance(vReal, uPilot);
    float fw = max(fwidth(d), 0.5);
    for (int i = 0; i < ${maxLinks}; i++) {
      if (uRangeOn[i] < 0.5) continue;
      float r = uRanges[i];
      float ring = 1.0 - smoothstep(0.0, 2.5 * fw, abs(d - r));
      col = mix(col, uColors[i], ring * 0.95);
      if (d > r) col = mix(col, col * 0.55 + uColors[i] * 0.12, 0.6);   // outside free-space range
    }
    if (cd >= 0.0) {                              // strip edge + the route line itself
      float fc = max(fwidth(cd), 0.3);
      col = mix(col, vec3(1.0), 0.55 * (1.0 - smoothstep(0.0, 2.0 * fc, uCorW - cd)));
      col = mix(col, vec3(1.0, 0.62, 0.1), 0.85 * (1.0 - smoothstep(fc, 2.5 * fc, cd)));
    }
    gl_FragColor = vec4(col, 1.0);   // all colour maths done directly in sRGB space
  }`;
