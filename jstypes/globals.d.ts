// The globals Odoo's own declarations do not cover.
//
// three.js is loaded as a plain asset — `arc_plan/static/lib/three/three.min.js`
// in the bundle — so it is a global, not an import, and nothing tells the
// editor what is on it. Typing it here turns every `THREE.Mesh`, every
// material parameter and every OrbitControls option into something with a
// signature and a docstring, which is the difference between writing the
// viewer and guessing at it.
//
// Pinned to 0.148 to match the r148 in static/lib: three renamed and removed
// enough between releases that types from a different version would describe
// a library that is not the one loading in the browser.

import type * as ThreeNamespace from "three";
import type { OrbitControls as OrbitControlsType } from "three/examples/jsm/controls/OrbitControls";

// OrbitControls is a separate file in three's own distribution, and the
// non-module build attaches it onto the THREE object rather than exporting
// it. @types/three does not describe that, because in a bundled project you
// would import it — so the global gets it added back here, which is what the
// viewers actually call.
type ThreeGlobal = typeof ThreeNamespace & {
  OrbitControls: typeof OrbitControlsType;
};

declare global {
  const THREE: ThreeGlobal;

  interface Window {
    THREE: ThreeGlobal;
    OrbitControls: typeof OrbitControlsType;
  }

  // Non-standard, and used on purpose: materials.js reads it to decide how
  // large a procedural texture it can afford. Chrome has it, Firefox does
  // not, which is why every read of it is guarded.
  interface Navigator {
    deviceMemory?: number;
  }
}

export {};
