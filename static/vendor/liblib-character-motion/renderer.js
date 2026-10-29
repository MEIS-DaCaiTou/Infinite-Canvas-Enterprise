/* Character placeholder renderer recovered from public 258ckt1vw9j5s.js.
 * Only module 975790 is adapted. Bundler bootstrap, other modules, and RUM are
 * excluded. Three r160 and GLTF/Draco loaders are local; assets never call Liblib.
 */
import * as t from "../js/three-0.160.0.module.js";
import { DRACOLoader } from "../three-addons-r160/loaders/DRACOLoader.js";
import { GLTFLoader } from "../three-addons-r160/loaders/GLTFLoader.js";
const r = { f: DRACOLoader },
  i = { f: GLTFLoader };
let o = {
  name: "CopyShader",
  uniforms: { tDiffuse: { value: null }, opacity: { value: 1 } },
  vertexShader: `

		varying vec2 vUv;

		void main() {

			vUv = uv;
			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,
  fragmentShader: `

		uniform float opacity;

		uniform sampler2D tDiffuse;

		varying vec2 vUv;

		void main() {

			vec4 texel = texture2D( tDiffuse, vUv );
			gl_FragColor = opacity * texel;


		}`,
};
var a = t;
class s {
  constructor() {
    ((this.isPass = !0),
      (this.enabled = !0),
      (this.needsSwap = !0),
      (this.clear = !1),
      (this.renderToScreen = !1));
  }
  setSize() {}
  render() {
    console.error("THREE.Pass: .render() must be implemented in derived pass.");
  }
  dispose() {}
}
let l = new a.OrthographicCamera(-1, 1, 1, -1, 0, 1);
class n extends a.BufferGeometry {
  constructor() {
    (super(),
      this.setAttribute(
        "position",
        new a.Float32BufferAttribute([-1, 3, 0, -1, -1, 0, 3, -1, 0], 3),
      ),
      this.setAttribute(
        "uv",
        new a.Float32BufferAttribute([0, 2, 0, 0, 2, 0], 2),
      ));
  }
}
let u = new n();
class d {
  constructor(e) {
    this._mesh = new a.Mesh(u, e);
  }
  dispose() {
    this._mesh.geometry.dispose();
  }
  render(e) {
    e.render(this._mesh, l);
  }
  get material() {
    return this._mesh.material;
  }
  set material(e) {
    this._mesh.material = e;
  }
}
class h extends s {
  constructor(e, r) {
    (super(),
      (this.textureID = void 0 !== r ? r : "tDiffuse"),
      e instanceof t.ShaderMaterial
        ? ((this.uniforms = e.uniforms), (this.material = e))
        : e &&
          ((this.uniforms = t.UniformsUtils.clone(e.uniforms)),
          (this.material = new t.ShaderMaterial({
            name: void 0 !== e.name ? e.name : "unspecified",
            defines: Object.assign({}, e.defines),
            uniforms: this.uniforms,
            vertexShader: e.vertexShader,
            fragmentShader: e.fragmentShader,
          }))),
      (this.fsQuad = new d(this.material)));
  }
  render(e, t, r) {
    (this.uniforms[this.textureID] &&
      (this.uniforms[this.textureID].value = r.texture),
      (this.fsQuad.material = this.material),
      this.renderToScreen
        ? e.setRenderTarget(null)
        : (e.setRenderTarget(t),
          this.clear &&
            e.clear(e.autoClearColor, e.autoClearDepth, e.autoClearStencil)),
      this.fsQuad.render(e));
  }
  dispose() {
    (this.material.dispose(), this.fsQuad.dispose());
  }
}
class c extends s {
  constructor(e, t) {
    (super(),
      (this.scene = e),
      (this.camera = t),
      (this.clear = !0),
      (this.needsSwap = !1),
      (this.inverse = !1));
  }
  render(e, t, r) {
    let i,
      o,
      a = e.getContext(),
      s = e.state;
    (s.buffers.color.setMask(!1),
      s.buffers.depth.setMask(!1),
      s.buffers.color.setLocked(!0),
      s.buffers.depth.setLocked(!0),
      this.inverse ? ((i = 0), (o = 1)) : ((i = 1), (o = 0)),
      s.buffers.stencil.setTest(!0),
      s.buffers.stencil.setOp(a.REPLACE, a.REPLACE, a.REPLACE),
      s.buffers.stencil.setFunc(a.ALWAYS, i, 0xffffffff),
      s.buffers.stencil.setClear(o),
      s.buffers.stencil.setLocked(!0),
      e.setRenderTarget(r),
      this.clear && e.clear(),
      e.render(this.scene, this.camera),
      e.setRenderTarget(t),
      this.clear && e.clear(),
      e.render(this.scene, this.camera),
      s.buffers.color.setLocked(!1),
      s.buffers.depth.setLocked(!1),
      s.buffers.color.setMask(!0),
      s.buffers.depth.setMask(!0),
      s.buffers.stencil.setLocked(!1),
      s.buffers.stencil.setFunc(a.EQUAL, 1, 0xffffffff),
      s.buffers.stencil.setOp(a.KEEP, a.KEEP, a.KEEP),
      s.buffers.stencil.setLocked(!0));
  }
}
class f extends s {
  constructor() {
    (super(), (this.needsSwap = !1));
  }
  render(e) {
    (e.state.buffers.stencil.setLocked(!1),
      e.state.buffers.stencil.setTest(!1));
  }
}
class m {
  constructor(e, r) {
    if (
      ((this.renderer = e),
      (this._pixelRatio = e.getPixelRatio()),
      void 0 === r)
    ) {
      let i = e.getSize(new t.Vector2());
      ((this._width = i.width),
        (this._height = i.height),
        ((r = new t.WebGLRenderTarget(
          this._width * this._pixelRatio,
          this._height * this._pixelRatio,
          { type: t.HalfFloatType },
        )).texture.name = "EffectComposer.rt1"));
    } else ((this._width = r.width), (this._height = r.height));
    ((this.renderTarget1 = r),
      (this.renderTarget2 = r.clone()),
      (this.renderTarget2.texture.name = "EffectComposer.rt2"),
      (this.writeBuffer = this.renderTarget1),
      (this.readBuffer = this.renderTarget2),
      (this.renderToScreen = !0),
      (this.passes = []),
      (this.copyPass = new h(o)),
      (this.copyPass.material.blending = t.NoBlending),
      (this.clock = new t.Clock()));
  }
  swapBuffers() {
    let e = this.readBuffer;
    ((this.readBuffer = this.writeBuffer), (this.writeBuffer = e));
  }
  addPass(e) {
    (this.passes.push(e),
      e.setSize(
        this._width * this._pixelRatio,
        this._height * this._pixelRatio,
      ));
  }
  insertPass(e, t) {
    (this.passes.splice(t, 0, e),
      e.setSize(
        this._width * this._pixelRatio,
        this._height * this._pixelRatio,
      ));
  }
  removePass(e) {
    let t = this.passes.indexOf(e);
    -1 !== t && this.passes.splice(t, 1);
  }
  isLastEnabledPass(e) {
    for (let t = e + 1; t < this.passes.length; t++)
      if (this.passes[t].enabled) return !1;
    return !0;
  }
  render(e) {
    void 0 === e && (e = this.clock.getDelta());
    let t = this.renderer.getRenderTarget(),
      r = !1;
    for (let t = 0, i = this.passes.length; t < i; t++) {
      let i = this.passes[t];
      if (!1 !== i.enabled) {
        if (
          ((i.renderToScreen =
            this.renderToScreen && this.isLastEnabledPass(t)),
          i.render(this.renderer, this.writeBuffer, this.readBuffer, e, r),
          i.needsSwap)
        ) {
          if (r) {
            let t = this.renderer.getContext(),
              r = this.renderer.state.buffers.stencil;
            (r.setFunc(t.NOTEQUAL, 1, 0xffffffff),
              this.copyPass.render(
                this.renderer,
                this.writeBuffer,
                this.readBuffer,
                e,
              ),
              r.setFunc(t.EQUAL, 1, 0xffffffff));
          }
          this.swapBuffers();
        }
        void 0 !== c &&
          (i instanceof c ? (r = !0) : i instanceof f && (r = !1));
      }
    }
    this.renderer.setRenderTarget(t);
  }
  reset(e) {
    if (void 0 === e) {
      let r = this.renderer.getSize(new t.Vector2());
      ((this._pixelRatio = this.renderer.getPixelRatio()),
        (this._width = r.width),
        (this._height = r.height),
        (e = this.renderTarget1.clone()).setSize(
          this._width * this._pixelRatio,
          this._height * this._pixelRatio,
        ));
    }
    (this.renderTarget1.dispose(),
      this.renderTarget2.dispose(),
      (this.renderTarget1 = e),
      (this.renderTarget2 = e.clone()),
      (this.writeBuffer = this.renderTarget1),
      (this.readBuffer = this.renderTarget2));
  }
  setSize(e, t) {
    ((this._width = e), (this._height = t));
    let r = this._width * this._pixelRatio,
      i = this._height * this._pixelRatio;
    (this.renderTarget1.setSize(r, i), this.renderTarget2.setSize(r, i));
    for (let e = 0; e < this.passes.length; e++) this.passes[e].setSize(r, i);
  }
  setPixelRatio(e) {
    ((this._pixelRatio = e), this.setSize(this._width, this._height));
  }
  dispose() {
    (this.renderTarget1.dispose(),
      this.renderTarget2.dispose(),
      this.copyPass.dispose());
  }
}
class v extends s {
  constructor(e, r, i = null, o = null, a = null) {
    (super(),
      (this.scene = e),
      (this.camera = r),
      (this.overrideMaterial = i),
      (this.clearColor = o),
      (this.clearAlpha = a),
      (this.clear = !0),
      (this.clearDepth = !1),
      (this.needsSwap = !1),
      (this._oldClearColor = new t.Color()));
  }
  render(e, t, r) {
    let i,
      o,
      a = e.autoClear;
    ((e.autoClear = !1),
      null !== this.overrideMaterial &&
        ((o = this.scene.overrideMaterial),
        (this.scene.overrideMaterial = this.overrideMaterial)),
      null !== this.clearColor &&
        (e.getClearColor(this._oldClearColor),
        e.setClearColor(this.clearColor)),
      null !== this.clearAlpha &&
        ((i = e.getClearAlpha()), e.setClearAlpha(this.clearAlpha)),
      !0 == this.clearDepth && e.clearDepth(),
      e.setRenderTarget(this.renderToScreen ? null : r),
      !0 === this.clear &&
        e.clear(e.autoClearColor, e.autoClearDepth, e.autoClearStencil),
      e.render(this.scene, this.camera),
      null !== this.clearColor && e.setClearColor(this._oldClearColor),
      null !== this.clearAlpha && e.setClearAlpha(i),
      null !== this.overrideMaterial && (this.scene.overrideMaterial = o),
      (e.autoClear = a));
  }
}
let g = {
  name: "LuminosityHighPassShader",
  shaderID: "luminosityHighPass",
  uniforms: {
    tDiffuse: { value: null },
    luminosityThreshold: { value: 1 },
    smoothWidth: { value: 1 },
    defaultColor: { value: new t.Color(0) },
    defaultOpacity: { value: 0 },
  },
  vertexShader: `

		varying vec2 vUv;

		void main() {

			vUv = uv;

			gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );

		}`,
  fragmentShader: `

		uniform sampler2D tDiffuse;
		uniform vec3 defaultColor;
		uniform float defaultOpacity;
		uniform float luminosityThreshold;
		uniform float smoothWidth;

		varying vec2 vUv;

		void main() {

			vec4 texel = texture2D( tDiffuse, vUv );

			vec3 luma = vec3( 0.299, 0.587, 0.114 );

			float v = dot( texel.xyz, luma );

			vec4 outputColor = vec4( defaultColor.rgb, defaultOpacity );

			float alpha = smoothstep( luminosityThreshold, luminosityThreshold + smoothWidth, v );

			gl_FragColor = mix( outputColor, texel, alpha );

		}`,
};
class p extends s {
  constructor(e, r, i, a) {
    (super(),
      (this.strength = void 0 !== r ? r : 1),
      (this.radius = i),
      (this.threshold = a),
      (this.resolution =
        void 0 !== e ? new t.Vector2(e.x, e.y) : new t.Vector2(256, 256)),
      (this.clearColor = new t.Color(0, 0, 0)),
      (this.renderTargetsHorizontal = []),
      (this.renderTargetsVertical = []),
      (this.nMips = 5));
    let s = Math.round(this.resolution.x / 2),
      l = Math.round(this.resolution.y / 2);
    ((this.renderTargetBright = new t.WebGLRenderTarget(s, l, {
      type: t.HalfFloatType,
    })),
      (this.renderTargetBright.texture.name = "UnrealBloomPass.bright"),
      (this.renderTargetBright.texture.generateMipmaps = !1));
    for (let e = 0; e < this.nMips; e++) {
      let r = new t.WebGLRenderTarget(s, l, { type: t.HalfFloatType });
      ((r.texture.name = "UnrealBloomPass.h" + e),
        (r.texture.generateMipmaps = !1),
        this.renderTargetsHorizontal.push(r));
      let i = new t.WebGLRenderTarget(s, l, { type: t.HalfFloatType });
      ((i.texture.name = "UnrealBloomPass.v" + e),
        (i.texture.generateMipmaps = !1),
        this.renderTargetsVertical.push(i),
        (s = Math.round(s / 2)),
        (l = Math.round(l / 2)));
    }
    ((this.highPassUniforms = t.UniformsUtils.clone(g.uniforms)),
      (this.highPassUniforms.luminosityThreshold.value = a),
      (this.highPassUniforms.smoothWidth.value = 0.01),
      (this.materialHighPassFilter = new t.ShaderMaterial({
        uniforms: this.highPassUniforms,
        vertexShader: g.vertexShader,
        fragmentShader: g.fragmentShader,
      })),
      (this.separableBlurMaterials = []));
    let n = [3, 5, 7, 9, 11];
    ((s = Math.round(this.resolution.x / 2)),
      (l = Math.round(this.resolution.y / 2)));
    for (let e = 0; e < this.nMips; e++)
      (this.separableBlurMaterials.push(this.getSeperableBlurMaterial(n[e])),
        (this.separableBlurMaterials[e].uniforms.invSize.value = new t.Vector2(
          1 / s,
          1 / l,
        )),
        (s = Math.round(s / 2)),
        (l = Math.round(l / 2)));
    ((this.compositeMaterial = this.getCompositeMaterial(this.nMips)),
      (this.compositeMaterial.uniforms.blurTexture1.value =
        this.renderTargetsVertical[0].texture),
      (this.compositeMaterial.uniforms.blurTexture2.value =
        this.renderTargetsVertical[1].texture),
      (this.compositeMaterial.uniforms.blurTexture3.value =
        this.renderTargetsVertical[2].texture),
      (this.compositeMaterial.uniforms.blurTexture4.value =
        this.renderTargetsVertical[3].texture),
      (this.compositeMaterial.uniforms.blurTexture5.value =
        this.renderTargetsVertical[4].texture),
      (this.compositeMaterial.uniforms.bloomStrength.value = r),
      (this.compositeMaterial.uniforms.bloomRadius.value = 0.1),
      (this.compositeMaterial.uniforms.bloomFactors.value = [
        1, 0.8, 0.6, 0.4, 0.2,
      ]),
      (this.bloomTintColors = [
        new t.Vector3(1, 1, 1),
        new t.Vector3(1, 1, 1),
        new t.Vector3(1, 1, 1),
        new t.Vector3(1, 1, 1),
        new t.Vector3(1, 1, 1),
      ]),
      (this.compositeMaterial.uniforms.bloomTintColors.value =
        this.bloomTintColors),
      (this.copyUniforms = t.UniformsUtils.clone(o.uniforms)),
      (this.blendMaterial = new t.ShaderMaterial({
        uniforms: this.copyUniforms,
        vertexShader: o.vertexShader,
        fragmentShader: o.fragmentShader,
        blending: t.AdditiveBlending,
        depthTest: !1,
        depthWrite: !1,
        transparent: !0,
      })),
      (this.enabled = !0),
      (this.needsSwap = !1),
      (this._oldClearColor = new t.Color()),
      (this.oldClearAlpha = 1),
      (this.basic = new t.MeshBasicMaterial()),
      (this.fsQuad = new d(null)));
  }
  dispose() {
    for (let e = 0; e < this.renderTargetsHorizontal.length; e++)
      this.renderTargetsHorizontal[e].dispose();
    for (let e = 0; e < this.renderTargetsVertical.length; e++)
      this.renderTargetsVertical[e].dispose();
    this.renderTargetBright.dispose();
    for (let e = 0; e < this.separableBlurMaterials.length; e++)
      this.separableBlurMaterials[e].dispose();
    (this.compositeMaterial.dispose(),
      this.blendMaterial.dispose(),
      this.basic.dispose(),
      this.fsQuad.dispose());
  }
  setSize(e, r) {
    let i = Math.round(e / 2),
      o = Math.round(r / 2);
    this.renderTargetBright.setSize(i, o);
    for (let e = 0; e < this.nMips; e++)
      (this.renderTargetsHorizontal[e].setSize(i, o),
        this.renderTargetsVertical[e].setSize(i, o),
        (this.separableBlurMaterials[e].uniforms.invSize.value = new t.Vector2(
          1 / i,
          1 / o,
        )),
        (i = Math.round(i / 2)),
        (o = Math.round(o / 2)));
  }
  render(e, t, r, i, o) {
    (e.getClearColor(this._oldClearColor),
      (this.oldClearAlpha = e.getClearAlpha()));
    let a = e.autoClear;
    ((e.autoClear = !1),
      e.setClearColor(this.clearColor, 0),
      o && e.state.buffers.stencil.setTest(!1),
      this.renderToScreen &&
        ((this.fsQuad.material = this.basic),
        (this.basic.map = r.texture),
        e.setRenderTarget(null),
        e.clear(),
        this.fsQuad.render(e)),
      (this.highPassUniforms.tDiffuse.value = r.texture),
      (this.highPassUniforms.luminosityThreshold.value = this.threshold),
      (this.fsQuad.material = this.materialHighPassFilter),
      e.setRenderTarget(this.renderTargetBright),
      e.clear(),
      this.fsQuad.render(e));
    let s = this.renderTargetBright;
    for (let t = 0; t < this.nMips; t++)
      ((this.fsQuad.material = this.separableBlurMaterials[t]),
        (this.separableBlurMaterials[t].uniforms.colorTexture.value =
          s.texture),
        (this.separableBlurMaterials[t].uniforms.direction.value =
          p.BlurDirectionX),
        e.setRenderTarget(this.renderTargetsHorizontal[t]),
        e.clear(),
        this.fsQuad.render(e),
        (this.separableBlurMaterials[t].uniforms.colorTexture.value =
          this.renderTargetsHorizontal[t].texture),
        (this.separableBlurMaterials[t].uniforms.direction.value =
          p.BlurDirectionY),
        e.setRenderTarget(this.renderTargetsVertical[t]),
        e.clear(),
        this.fsQuad.render(e),
        (s = this.renderTargetsVertical[t]));
    ((this.fsQuad.material = this.compositeMaterial),
      (this.compositeMaterial.uniforms.bloomStrength.value = this.strength),
      (this.compositeMaterial.uniforms.bloomRadius.value = this.radius),
      (this.compositeMaterial.uniforms.bloomTintColors.value =
        this.bloomTintColors),
      e.setRenderTarget(this.renderTargetsHorizontal[0]),
      e.clear(),
      this.fsQuad.render(e),
      (this.fsQuad.material = this.blendMaterial),
      (this.copyUniforms.tDiffuse.value =
        this.renderTargetsHorizontal[0].texture),
      o && e.state.buffers.stencil.setTest(!0),
      this.renderToScreen ? e.setRenderTarget(null) : e.setRenderTarget(r),
      this.fsQuad.render(e),
      e.setClearColor(this._oldClearColor, this.oldClearAlpha),
      (e.autoClear = a));
  }
  getSeperableBlurMaterial(e) {
    let r = [];
    for (let t = 0; t < e; t++)
      r.push((0.39894 * Math.exp((-0.5 * t * t) / (e * e))) / e);
    return new t.ShaderMaterial({
      defines: { KERNEL_RADIUS: e },
      uniforms: {
        colorTexture: { value: null },
        invSize: { value: new t.Vector2(0.5, 0.5) },
        direction: { value: new t.Vector2(0.5, 0.5) },
        gaussianCoefficients: { value: r },
      },
      vertexShader: `varying vec2 vUv;
				void main() {
					vUv = uv;
					gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
				}`,
      fragmentShader: `#include <common>
				varying vec2 vUv;
				uniform sampler2D colorTexture;
				uniform vec2 invSize;
				uniform vec2 direction;
				uniform float gaussianCoefficients[KERNEL_RADIUS];

				void main() {
					float weightSum = gaussianCoefficients[0];
					vec3 diffuseSum = texture2D( colorTexture, vUv ).rgb * weightSum;
					for( int i = 1; i < KERNEL_RADIUS; i ++ ) {
						float x = float(i);
						float w = gaussianCoefficients[i];
						vec2 uvOffset = direction * invSize * x;
						vec3 sample1 = texture2D( colorTexture, vUv + uvOffset ).rgb;
						vec3 sample2 = texture2D( colorTexture, vUv - uvOffset ).rgb;
						diffuseSum += (sample1 + sample2) * w;
						weightSum += 2.0 * w;
					}
					gl_FragColor = vec4(diffuseSum/weightSum, 1.0);
				}`,
    });
  }
  getCompositeMaterial(e) {
    return new t.ShaderMaterial({
      defines: { NUM_MIPS: e },
      uniforms: {
        blurTexture1: { value: null },
        blurTexture2: { value: null },
        blurTexture3: { value: null },
        blurTexture4: { value: null },
        blurTexture5: { value: null },
        bloomStrength: { value: 1 },
        bloomFactors: { value: null },
        bloomTintColors: { value: null },
        bloomRadius: { value: 0 },
      },
      vertexShader: `varying vec2 vUv;
				void main() {
					vUv = uv;
					gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
				}`,
      fragmentShader: `varying vec2 vUv;
				uniform sampler2D blurTexture1;
				uniform sampler2D blurTexture2;
				uniform sampler2D blurTexture3;
				uniform sampler2D blurTexture4;
				uniform sampler2D blurTexture5;
				uniform float bloomStrength;
				uniform float bloomRadius;
				uniform float bloomFactors[NUM_MIPS];
				uniform vec3 bloomTintColors[NUM_MIPS];

				float lerpBloomFactor(const in float factor) {
					float mirrorFactor = 1.2 - factor;
					return mix(factor, mirrorFactor, bloomRadius);
				}

				void main() {
					gl_FragColor = bloomStrength * ( lerpBloomFactor(bloomFactors[0]) * vec4(bloomTintColors[0], 1.0) * texture2D(blurTexture1, vUv) +
						lerpBloomFactor(bloomFactors[1]) * vec4(bloomTintColors[1], 1.0) * texture2D(blurTexture2, vUv) +
						lerpBloomFactor(bloomFactors[2]) * vec4(bloomTintColors[2], 1.0) * texture2D(blurTexture3, vUv) +
						lerpBloomFactor(bloomFactors[3]) * vec4(bloomTintColors[3], 1.0) * texture2D(blurTexture4, vUv) +
						lerpBloomFactor(bloomFactors[4]) * vec4(bloomTintColors[4], 1.0) * texture2D(blurTexture5, vUv) );
				}`,
    });
  }
}
((p.BlurDirectionX = new t.Vector2(1, 0)),
  (p.BlurDirectionY = new t.Vector2(0, 1)));
const b = {
  f: (renderer) => {
    renderer.renderLists.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  },
};
let w = { columns: 48, rows: 48, lineWidth: 0.05 },
  C = { speed: 1.8, duration: 2.5, pause: 0.15 },
  S = {
    bandHeight: 0.255,
    edgeSoftness: 0.035,
    depthContour: 0.92,
    silhouetteWrap: 0.04,
    noise: 0.02,
    grain: 0.46,
  },
  y = {
    dark: {
      grid: {
        surfaceColor: "#5c5c5c",
        color: "#ffffff",
        ...w,
        opacity: 0.03,
        rimStrength: 0.83,
        rimPower: 1.05,
        bodyRimStrength: 0.5,
        bodyRimPower: 0.5,
        shading: 0,
      },
      loadingGrid: {
        color: "#ffffff",
        ...w,
        opacity: 0.03,
        rimStrength: 0.75,
        rimPower: 1,
      },
      scan: {
        ...C,
        ...S,
        litBrightness: 0.5,
        darkBrightness: 0,
        rimStrength: 0.3,
        rimPower: 1.45,
        rgbSplit: 0.3,
        rimNoise: 0,
        color: "#ffffff",
        rimColor: "#ffffff",
        surfaceColor: "#363636",
        shading: 0,
      },
    },
    light: {
      grid: {
        surfaceColor: "#efefef",
        color: "#3a3a3a",
        ...w,
        opacity: 0.07,
        rimStrength: 0.6,
        rimPower: 1.2,
        bodyRimStrength: 1.3,
        bodyRimPower: 1.3,
        shading: 0.45,
      },
      loadingGrid: {
        color: "#3a3a3a",
        ...w,
        opacity: 0.07,
        rimStrength: 0.5,
        rimPower: 1.2,
      },
      scan: {
        ...C,
        ...S,
        litBrightness: 1,
        darkBrightness: 0,
        rimStrength: 0.3,
        rimPower: 2.4,
        rgbSplit: 0,
        rimNoise: 0,
        color: "#ffffff",
        rimColor: "#3a3a3a",
        surfaceColor: "#efefef",
        shading: 0.45,
      },
    },
  };
function x(e) {
  return y[e].loadingGrid;
}
function T(e) {
  return y[e].scan;
}
function R(e) {
  return +("light" === e);
}
let M = `
#include <common>
varying vec2 vUv;
uniform sampler2D colorTexture;
uniform vec2 invSize;
uniform vec2 direction;
uniform float gaussianCoefficients[KERNEL_RADIUS];

void main() {
  float weightSum = gaussianCoefficients[0];
  vec4 diffuseSum = texture2D(colorTexture, vUv) * weightSum;
  for (int i = 1; i < KERNEL_RADIUS; i++) {
    float x = float(i);
    float w = gaussianCoefficients[i];
    vec2 uvOffset = direction * invSize * x;
    vec4 sample1 = texture2D(colorTexture, vUv + uvOffset);
    vec4 sample2 = texture2D(colorTexture, vUv - uvOffset);
    diffuseSum += (sample1 + sample2) * w;
    weightSum += 2.0 * w;
  }
  gl_FragColor = diffuseSum / weightSum;
}
`,
  B = {
    uniforms: { tDiffuse: { value: null } },
    vertexShader: `
    varying vec2 vUv;

    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
    fragmentShader: `
    uniform sampler2D tDiffuse;
    varying vec2 vUv;

    float ign(vec2 point) {
      return fract(52.9829189 * fract(dot(point, vec2(0.06711056, 0.00583715))));
    }

    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      float dither = (ign(gl_FragCoord.xy) + ign(gl_FragCoord.xy + 19.19) - 1.0) / 255.0;
      float alpha = color.a + dither;
      if (alpha < 0.5 / 255.0) {
        gl_FragColor = vec4(0.0);
        return;
      }
      gl_FragColor = vec4(max(color.rgb + dither, vec3(0.0)), clamp(alpha, 0.0, 1.0));
    }
  `,
  },
  P = `
uniform float uMinY;
uniform float uMaxY;

varying float vBodyY;
varying vec2 vClipUv;
varying vec3 vObjectPosition;
varying vec2 vSurfaceUv;
varying vec3 vViewNormal;
varying vec3 vViewPosition;

void main() {
  vObjectPosition = position;
  vSurfaceUv = uv;
  float bodyHeight = max(uMaxY - uMinY, 0.0001);
  vBodyY = clamp((position.y - uMinY) / bodyHeight, 0.0, 1.0);

  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  vViewPosition = -mvPosition.xyz;
  vViewNormal = normalize(normalMatrix * normal);
  gl_Position = projectionMatrix * mvPosition;
  vClipUv = gl_Position.xy / max(gl_Position.w, 0.0001) * 0.5 + 0.5;
}
`,
  k = `
uniform vec2 uMouse;
uniform float uAspect;
uniform vec2 uCardOriginClip;
uniform float uCardToCanvasX;
uniform float uCardToCanvasY;
uniform float uSpotlightHover;
uniform float uSpotlightRadius;
uniform float uSpotlightSoftness;
uniform float uSpotlightStrength;
uniform float uLightLift;

float characterShade(vec3 viewNormal, float shade) {
  vec3 lightDir = normalize(vec3(-0.35, 0.55, 0.75));
  float lambert = clamp(dot(viewNormal, lightDir) * 0.5 + 0.5, 0.0, 1.0);
  return 1.0 - (1.0 - lambert) * shade;
}

vec3 characterCompose(vec3 surface, vec3 inkColor, float mask, float lift, float ink) {
  vec3 additive = (surface + inkColor * mask) * lift;
  float liftAmount = max(lift - 1.0, 0.0);
  vec3 inkBase = mix(surface, vec3(1.0), clamp(liftAmount * 0.35, 0.0, 1.0));
  vec3 inked = mix(inkBase, inkColor, clamp(mask * (1.0 + liftAmount * 0.6), 0.0, 1.0));
  return mix(additive, inked, ink);
}

float characterSpotlightLift(float facing) {
  vec2 cardUv = vec2(
    (vClipUv.x - uCardOriginClip.x) / max(uCardToCanvasX, 0.0001),
    (vClipUv.y - uCardOriginClip.y) / max(uCardToCanvasY, 0.0001)
  );
  vec2 spotlightCenter = vec2(0.5 + uMouse.x * 0.5, 0.5 - uMouse.y * 0.5);
  vec2 spotlightDelta = cardUv - spotlightCenter;
  spotlightDelta.x *= uAspect;
  float spotlightDistance = length(spotlightDelta);
  float spotlight = 1.0 - smoothstep(
    uSpotlightRadius,
    uSpotlightRadius + uSpotlightSoftness,
    spotlightDistance
  );
  return 1.0
    + facing * uLightLift * uSpotlightHover
    + spotlight * uSpotlightStrength * uSpotlightHover;
}
`,
  _ =
    `
#include <common>
#include <dithering_pars_fragment>

uniform float uTime;
uniform float uProgress;
uniform float uVisibility;
uniform float uBandHeight;
uniform float uEdgeSoftness;
uniform float uDepthContour;
uniform float uSilhouetteWrap;
uniform float uNoiseAmount;
uniform float uGrain;
uniform float uLitBrightness;
uniform float uDarkBrightness;
uniform float uRimStrength;
uniform float uRimPower;
uniform float uBodyRimBlend;
uniform float uRgbSplit;
uniform float uRimNoise;
uniform vec3 uColor;
uniform vec3 uSurfaceColor;
uniform vec3 uGridColor;
uniform float uGridColumns;
uniform float uGridRows;
uniform float uGridLineWidth;
uniform float uGridLineAA;
uniform float uGridOpacity;
uniform float uGridRimStrength;
uniform float uGridRimPower;
uniform float uGridRimFill;
uniform float uInk;
uniform float uShade;
uniform vec3 uRimColor;

varying float vBodyY;
varying vec2 vClipUv;
varying vec3 vObjectPosition;
varying vec2 vSurfaceUv;
varying vec3 vViewNormal;
varying vec3 vViewPosition;

float hash21(vec2 point) {
  point = fract(point * vec2(123.34, 456.21));
  point += dot(point, point + 45.32);
  return fract(point.x * point.y);
}

float noise21(vec2 point) {
  vec2 cell = floor(point);
  vec2 positionInCell = fract(point);
  positionInCell = positionInCell * positionInCell * (3.0 - 2.0 * positionInCell);
  return mix(
    mix(hash21(cell), hash21(cell + vec2(1.0, 0.0)), positionInCell.x),
    mix(hash21(cell + vec2(0.0, 1.0)), hash21(cell + vec2(1.0, 1.0)), positionInCell.x),
    positionInCell.y
  );
}

float fbm(vec2 point) {
  float value = 0.0;
  float amplitude = 0.5;
  for (int index = 0; index < 4; index++) {
    value += noise21(point) * amplitude;
    point = point * 2.03 + 13.17;
    amplitude *= 0.5;
  }
  return value;
}

float gauss(float value, float sigma) {
  return exp(-value * value / max(2.0 * sigma * sigma, 0.0001));
}

float fogMask(float distanceToBand, float halfBand, float softness) {
  float sigmaLead = max(halfBand * 0.78 + softness * 0.55, 0.003);
  float sigmaTrail = max(halfBand * 1.18 + softness, 0.003);
  float sigma = distanceToBand > 0.0 ? sigmaTrail : sigmaLead;
  float core = gauss(distanceToBand, sigma * 0.62);
  float volume = gauss(distanceToBand, sigma);
  float veil = gauss(distanceToBand, sigma * 1.85);
  return core * 0.42 + volume * 0.4 + veil * 0.22;
}

float surfaceGrid(vec2 surfaceUv) {
  vec2 density = vec2(uGridColumns, uGridRows);
  vec2 enabled = step(vec2(0.5), density);
  vec2 coordinate = surfaceUv * max(density, vec2(1.0));
  vec2 derivative = max(fwidth(coordinate), vec2(0.0001));
  vec2 distanceToLine = abs(fract(coordinate - 0.5) - 0.5) / derivative;
  vec2 lines = 1.0 - smoothstep(
    vec2(uGridLineWidth),
    vec2(uGridLineWidth) + vec2(max(uGridLineAA, 0.2)),
    distanceToLine
  );
  return max(lines.x * enabled.x, lines.y * enabled.y) * step(0.0001, uGridLineWidth);
}
` +
    k +
    `
void main() {
  vec3 normal = normalize(vViewNormal);
  vec3 viewDir = normalize(vViewPosition);
  float facing = clamp(abs(dot(normal, viewDir)), 0.0, 1.0);

  vec2 mistUv = vObjectPosition.xz * 1.65 + vObjectPosition.yy * 0.35;
  mistUv += vec2(uTime * 0.028, -uTime * 0.021);
  float mist = fbm(mistUv);
  float mistFine = fbm(mistUv * 2.4 + 7.13);

  vec2 edgeUv = vec2(vObjectPosition.x * 1.2, vBodyY * 1.35);
  edgeUv += vec2(uTime * 0.01, 0.0);
  float edgeWobble = (fbm(edgeUv) - 0.5) * (0.05 + uNoiseAmount * 1.6);
  float scanField = vBodyY + edgeWobble;

  float halfBand = max(uBandHeight * 0.5, 0.0001);
  float sigmaLead = max(halfBand * 0.78 + uEdgeSoftness * 0.55, 0.003);
  float sigmaTrail = max(halfBand * 1.18 + uEdgeSoftness, 0.003);
  float overshootStart = sigmaLead * 2.2 + 0.05;
  float overshootEnd = sigmaTrail * 2.2 + 0.05;
  float scanY = mix(1.0 + overshootStart, -overshootEnd, uProgress);
  float signedDist = scanField - scanY;
  float mistMix = mix(1.0, 0.78 + mist * 0.28 + mistFine * 0.12, uGrain);

  float split = uRgbSplit * 0.048;
  float fogR = fogMask(signedDist - split, halfBand, uEdgeSoftness) * mistMix;
  float fogG = fogMask(signedDist, halfBand, uEdgeSoftness) * mistMix;
  float fogB = fogMask(signedDist + split, halfBand, uEdgeSoftness) * mistMix;

  vec3 lightDir = normalize(vec3(-0.08, 0.1, 0.99));
  float wrapAmount = mix(0.38, 0.7, clamp(uDepthContour / 2.2, 0.0, 1.0));
  float wrap = clamp(dot(normal, lightDir) * wrapAmount + (1.0 - wrapAmount) * 0.5, 0.0, 1.0);
  float form = pow(wrap, 0.82);
  float viewFill = mix(0.28, 1.0, pow(facing, 0.52));
  float surface = form * viewFill;
  surface *= 1.0 + pow(1.0 - facing, 1.35) * uSilhouetteWrap * 5.0;

  vec2 rimUv = vec2(
    atan(vObjectPosition.x, vObjectPosition.z) * 1.85,
    vBodyY * 7.2
  );
  rimUv += vec2(uTime * 0.09, uTime * 0.052);
  float rimNoise = fbm(rimUv);
  float rimNoiseFine = fbm(rimUv * 3.4 + 21.7);
  float facingBreak = clamp(facing + (rimNoise - 0.5) * uRimNoise * 0.28, 0.0, 1.0);
  float rimTight = pow(1.0 - facingBreak, uRimPower);
  float rimHalo = pow(1.0 - facingBreak, max(uRimPower * 0.48, 0.4));
  float rimBreak = mix(1.0, 0.42 + rimNoise * 0.82 + rimNoiseFine * 0.28, uRimNoise);
  float staticBodyRim = pow(1.0 - facing, uRimPower) * uRimStrength * 0.22;
  float loadingBodyRim = (rimTight * 0.78 + rimHalo * 0.32) * uRimStrength * rimBreak;
  float bodyRim = mix(staticBodyRim, loadingBodyRim, uBodyRimBlend);

  float darkBody = uDarkBrightness * 0.42;
  vec3 bandLight = vec3(fogR, fogG, fogB) * uLitBrightness * surface;
  float grid = surfaceGrid(vSurfaceUv);
  float gridRim = pow(1.0 - facing, uGridRimPower) * uGridRimStrength;
  float gridEnergyMask = grid * (0.72 + grid * 0.42 + gridRim) + gridRim * uGridRimFill;
  vec3 gridEnergy = uGridColor * gridEnergyMask * uGridOpacity;

  float lift = characterSpotlightLift(facing);
  vec3 base = uSurfaceColor * characterShade(normal, uShade);
  vec3 additive = (base
    + uColor * (darkBody + bodyRim)
    + bandLight * uVisibility * uColor
    + gridEnergy) * lift;
  float liftAmount = max(lift - 1.0, 0.0);
  vec3 inkBase = mix(base, vec3(1.0), clamp(liftAmount * 0.35, 0.0, 1.0));
  float inkLift = 1.0 + liftAmount * 0.6;
  vec3 inked = mix(inkBase, uRimColor, clamp((darkBody + bodyRim) * inkLift, 0.0, 1.0));
  inked = mix(inked, uColor, clamp(bandLight * uVisibility * inkLift, 0.0, 1.0));
  inked = mix(inked, uGridColor, clamp(gridEnergyMask * uGridOpacity * inkLift, 0.0, 1.0));
  vec3 energy = mix(additive, inked, uInk);
  gl_FragColor = vec4(energy, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
  #include <dithering_fragment>
}
`,
  U =
    `
uniform vec3 uColor;
uniform vec3 uSurfaceColor;
uniform float uColumns;
uniform float uRows;
uniform float uLineWidth;
uniform float uLineAA;
uniform float uOpacity;
uniform float uRimStrength;
uniform float uRimPower;
uniform float uBodyRimStrength;
uniform float uBodyRimPower;
uniform float uInk;
uniform float uShade;

varying vec2 vClipUv;
varying vec2 vSurfaceUv;
varying vec3 vViewNormal;
varying vec3 vViewPosition;

float surfaceGrid(vec2 surfaceUv) {
  vec2 density = vec2(uColumns, uRows);
  vec2 enabled = step(vec2(0.5), density);
  vec2 coordinate = surfaceUv * max(density, vec2(1.0));
  vec2 derivative = max(fwidth(coordinate), vec2(0.0001));
  vec2 distanceToLine = abs(fract(coordinate - 0.5) - 0.5) / derivative;
  vec2 lines = 1.0 - smoothstep(
    vec2(uLineWidth),
    vec2(uLineWidth) + vec2(max(uLineAA, 0.2)),
    distanceToLine
  );
  return max(lines.x * enabled.x, lines.y * enabled.y) * step(0.0001, uLineWidth);
}
` +
    k +
    `
void main() {
  float grid = surfaceGrid(vSurfaceUv);
  vec3 viewNormal = normalize(vViewNormal);
  vec3 viewDirection = normalize(vViewPosition);
  float facing = clamp(abs(dot(viewNormal, viewDirection)), 0.0, 1.0);
  float gridRim = pow(1.0 - facing, uRimPower) * uRimStrength;
  float bodyRim = pow(1.0 - facing, uBodyRimPower) * uBodyRimStrength;
  float gridMask = grid * uOpacity * (0.72 + grid * 0.42 + gridRim);
  float bodyRimMask = bodyRim * 0.22;
  vec3 base = uSurfaceColor * characterShade(viewNormal, uShade);
  vec3 energy = characterCompose(base, uColor, gridMask + bodyRimMask, characterSpotlightLift(facing), uInk);
  gl_FragColor = vec4(energy, 1.0);
  #include <colorspace_fragment>
}
`;
let D = "/static/vendor/liblib-character-motion/midwam-human.glb",
  A = "/static/vendor/liblib-character-motion/draco/",
  G = 1 / 3;
function E() {
  return {
    uMouse: { value: new t.Vector2() },
    uAspect: { value: 1 },
    uCardOriginClip: { value: new t.Vector2() },
    uCardToCanvasX: { value: 1 },
    uCardToCanvasY: { value: 1 },
    uSpotlightHover: { value: 0 },
    uSpotlightRadius: { value: 0.04 },
    uSpotlightSoftness: { value: 0.18 },
    uSpotlightStrength: { value: 0.1 },
    uLightLift: { value: 0.06 },
  };
}
function F(e) {
  let t = T("dark"),
    r = t.duration + t.pause,
    i = ((e % r) + r) % r;
  return i < t.duration
    ? { progress: i / t.duration, visibility: 1 }
    : { progress: 0, visibility: 0 };
}
async function O() {
  let e = new r.f();
  (e.setDecoderPath(A), e.setWorkerLimit(1));
  let o = new i.f();
  o.setDRACOLoader(e);
  try {
    let e = await o.loadAsync(D),
      r = null;
    if (
      (e.scene.traverse((e) => {
        !r && e instanceof t.Mesh && (r = e);
      }),
      !r)
    )
      throw Error("Character generation model has no mesh");
    let i = r.geometry.clone();
    return (
      i.center(),
      i.rotateY(-(0.5 * Math.PI)),
      i.attributes.normal || i.computeVertexNormals(),
      i.computeBoundingBox(),
      i.computeBoundingSphere(),
      i
    );
  } finally {
    e.dispose();
  }
}
async function N(e, { reduceMotion: r = !1, theme: i = "dark" } = {}) {
  let o,
    a,
    s = await O(),
    l = s.boundingBox;
  if (!l)
    throw (s.dispose(), Error("Character generation model has no bounds"));
  let n =
    ((a = navigator.deviceMemory),
    /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ||
      ("number" == typeof a && a <= 4) ||
      !!window.matchMedia?.("(pointer: coarse)").matches);
  try {
    o = new t.WebGLRenderer({
      canvas: e,
      alpha: !0,
      antialias: !1,
      premultipliedAlpha: !1,
      powerPreference: n ? "default" : "high-performance",
    });
  } catch (e) {
    throw (s.dispose(), e);
  }
  (o.setClearColor(0, 0),
    (o.outputColorSpace = t.SRGBColorSpace),
    (o.toneMapping = t.ACESFilmicToneMapping),
    (o.toneMappingExposure = 1));
  let u = new t.Scene(),
    d = new t.PerspectiveCamera(20, 1, 0.1, 200),
    c = i,
    f = y[c].grid,
    g = x(c),
    w = T(c),
    C = R(c),
    S = new t.Color(f.surfaceColor),
    k = new t.Color(w.surfaceColor),
    L = new t.Color(f.color),
    D = new t.Color(w.color),
    A = new t.Color(w.rimColor),
    I = {
      uColor: { value: new t.Color(f.color) },
      uSurfaceColor: { value: new t.Color(f.surfaceColor) },
      uColumns: { value: f.columns },
      uRows: { value: f.rows },
      uLineWidth: { value: f.lineWidth },
      uLineAA: { value: 1 },
      uOpacity: { value: f.opacity },
      uRimStrength: { value: f.rimStrength },
      uRimPower: { value: f.rimPower },
      uBodyRimStrength: { value: f.bodyRimStrength },
      uBodyRimPower: { value: f.bodyRimPower },
      uInk: { value: C },
      uShade: { value: f.shading },
      uMinY: { value: l.min.y },
      uMaxY: { value: l.max.y },
      ...E(),
    },
    V = {
      uTime: { value: 0 },
      uProgress: { value: 0 },
      uVisibility: { value: 1 },
      uBandHeight: { value: w.bandHeight },
      uEdgeSoftness: { value: w.edgeSoftness },
      uDepthContour: { value: w.depthContour },
      uSilhouetteWrap: { value: w.silhouetteWrap },
      uNoiseAmount: { value: w.noise },
      uGrain: { value: w.grain },
      uLitBrightness: { value: w.litBrightness },
      uDarkBrightness: { value: w.darkBrightness },
      uRimStrength: { value: w.rimStrength },
      uRimPower: { value: w.rimPower },
      uBodyRimBlend: { value: 1 },
      uRgbSplit: { value: w.rgbSplit },
      uRimNoise: { value: w.rimNoise },
      uColor: { value: new t.Color(w.color) },
      uSurfaceColor: { value: new t.Color(w.surfaceColor) },
      uGridColor: { value: new t.Color(g.color) },
      uGridColumns: { value: g.columns },
      uGridRows: { value: g.rows },
      uGridLineWidth: { value: g.lineWidth },
      uGridLineAA: { value: 1 },
      uGridOpacity: { value: g.opacity },
      uGridRimStrength: { value: g.rimStrength },
      uGridRimPower: { value: g.rimPower },
      uGridRimFill: { value: 0.9 },
      uInk: { value: C },
      uShade: { value: w.shading },
      uRimColor: { value: new t.Color(w.rimColor) },
      uMinY: { value: l.min.y },
      uMaxY: { value: l.max.y },
      ...E(),
    },
    W = new t.ShaderMaterial({
      uniforms: I,
      vertexShader: P,
      fragmentShader: U,
      side: t.FrontSide,
      depthTest: !0,
      depthWrite: !0,
      toneMapped: !1,
    }),
    z = new t.ShaderMaterial({
      uniforms: V,
      vertexShader: P,
      fragmentShader: _,
      side: t.FrontSide,
      depthTest: !0,
      depthWrite: !0,
      toneMapped: !1,
    }),
    H = new t.Mesh(s, W);
  u.add(H);
  let Y = new t.WebGLRenderTarget(1, 1, {
      type: t.HalfFloatType,
      samples: Math.min(n ? 2 : 4, o.capabilities.maxSamples || 0),
    }),
    j = new m(o, Y),
    Q = new v(u, d),
    q = (function () {
      let e = new p(new t.Vector2(1, 1), 1.5 * G, 0.8, 0.05);
      for (let t of e.separableBlurMaterials)
        ((t.fragmentShader = M), (t.needsUpdate = !0));
      e.highPassUniforms.smoothWidth.value = 0.18;
      let r = e.blendMaterial;
      return (
        (r.blending = t.CustomBlending),
        (r.blendEquation = t.AddEquation),
        (r.blendSrc = t.OneFactor),
        (r.blendDst = t.OneFactor),
        (r.blendEquationAlpha = t.AddEquation),
        (r.blendSrcAlpha = t.OneFactor),
        (r.blendDstAlpha = t.OneMinusSrcAlphaFactor),
        (r.needsUpdate = !0),
        e
      );
    })(),
    K = new h(B);
  (j.addPass(Q), j.addPass(q), j.addPass(K), (q.enabled = !1));
  let X = "pending",
    J = 0,
    Z = !1,
    $ = 0,
    ee = 0,
    et = 0,
    er = 0,
    ei = 0,
    eo = 0,
    ea = 0,
    es = 0,
    el = 0,
    en = 1,
    eu = 0,
    ed = 0,
    eh = 0,
    ec = () => y[c].grid,
    ef = () => {
      let e = ec();
      (I.uColor.value.set(e.color),
        I.uSurfaceColor.value.set(e.surfaceColor),
        (I.uColumns.value = e.columns),
        (I.uRows.value = e.rows),
        (I.uLineWidth.value = e.lineWidth),
        (I.uOpacity.value = e.opacity),
        (I.uRimStrength.value = e.rimStrength),
        (I.uRimPower.value = e.rimPower),
        (I.uBodyRimStrength.value = e.bodyRimStrength),
        (I.uBodyRimPower.value = e.bodyRimPower),
        (I.uShade.value = e.shading));
    },
    em = (e) => {
      if ("light" === c) {
        ((q.enabled = !1),
          (q.strength = 0),
          (q.threshold = 0.22),
          (q.radius = 0.8));
        return;
      }
      let r = t.MathUtils.clamp(e, 0, 1);
      ((q.enabled = r > 0),
        (q.strength = 1.5 * G * r),
        (q.threshold = t.MathUtils.lerp(0.22, 0.05, r)),
        (q.radius = 0.8));
    },
    ev = () => {
      let e = T(c),
        t = x(c),
        r = F(ee);
      ((V.uTime.value = ee),
        (V.uProgress.value = r.progress),
        (V.uVisibility.value = r.visibility),
        V.uSurfaceColor.value.copy(k),
        V.uColor.value.copy(D),
        V.uRimColor.value.copy(A),
        (V.uRimStrength.value = e.rimStrength),
        (V.uRimPower.value = e.rimPower),
        (V.uBodyRimBlend.value = 1),
        (V.uBandHeight.value = e.bandHeight),
        (V.uEdgeSoftness.value = e.edgeSoftness),
        (V.uDepthContour.value = e.depthContour),
        (V.uSilhouetteWrap.value = e.silhouetteWrap),
        (V.uNoiseAmount.value = e.noise),
        (V.uGrain.value = e.grain),
        (V.uLitBrightness.value = e.litBrightness),
        (V.uDarkBrightness.value = e.darkBrightness),
        (V.uRgbSplit.value = e.rgbSplit),
        (V.uRimNoise.value = e.rimNoise),
        V.uGridColor.value.set(t.color),
        (V.uGridColumns.value = t.columns),
        (V.uGridRows.value = t.rows),
        (V.uGridLineWidth.value = t.lineWidth),
        (V.uGridOpacity.value = t.opacity),
        (V.uGridRimStrength.value = t.rimStrength),
        (V.uGridRimPower.value = t.rimPower),
        (V.uGridRimFill.value = 0.9),
        (V.uShade.value = e.shading),
        em(1));
    },
    eg = (e) => {
      let r = t.MathUtils.clamp(e, 0, 1),
        i = ec(),
        o = T(c),
        a = x(c),
        s = F(ee);
      (V.uSurfaceColor.value.copy(S).lerp(k, r),
        V.uColor.value.copy(L).lerp(D, r),
        V.uRimColor.value.copy(L).lerp(A, r),
        (V.uRimStrength.value = t.MathUtils.lerp(
          i.bodyRimStrength,
          o.rimStrength,
          r,
        )),
        (V.uRimPower.value = t.MathUtils.lerp(i.bodyRimPower, o.rimPower, r)),
        (V.uGridRimStrength.value = t.MathUtils.lerp(
          i.rimStrength,
          a.rimStrength,
          r,
        )),
        (V.uGridRimPower.value = t.MathUtils.lerp(i.rimPower, a.rimPower, r)),
        V.uGridColor.value.set(a.color),
        (V.uGridOpacity.value = t.MathUtils.lerp(i.opacity, a.opacity, r)),
        (V.uVisibility.value = s.visibility * r),
        (V.uBandHeight.value = o.bandHeight * r),
        (V.uEdgeSoftness.value = o.edgeSoftness * r),
        (V.uDepthContour.value = o.depthContour * r),
        (V.uSilhouetteWrap.value = o.silhouetteWrap * r),
        (V.uNoiseAmount.value = o.noise * r),
        (V.uGrain.value = o.grain * r),
        (V.uLitBrightness.value = o.litBrightness * r),
        (V.uDarkBrightness.value = o.darkBrightness * r),
        (V.uRgbSplit.value = o.rgbSplit * r),
        (V.uRimNoise.value = o.rimNoise * r),
        (V.uBodyRimBlend.value = r),
        (V.uGridRimFill.value = 0.9 * r),
        (V.uShade.value = t.MathUtils.lerp(i.shading, o.shading, r)),
        (V.uProgress.value = s.progress),
        (V.uTime.value = ee),
        em(r));
    },
    ep = () => {
      let t = e.parentElement?.parentElement ?? e.parentElement,
        r = e
          .closest("[data-character-generation-motion]")
          ?.querySelector("[data-character-model-hitbox]"),
        i = e.getBoundingClientRect(),
        o = r?.getBoundingClientRect() ?? t?.getBoundingClientRect() ?? i,
        a = Math.max(i.width, 1e-4),
        s = Math.max(i.height, 1e-4),
        l = (o.left - i.left) / a,
        n = (i.bottom - o.bottom) / s,
        u = o.width / a,
        h = o.height / s,
        c = o.height > 0.5 ? o.width / o.height : d.aspect || 1;
      for (let e of [I, V])
        (e.uMouse.value.set(er, ei),
          (e.uAspect.value = c),
          e.uCardOriginClip.value.set(l, n),
          (e.uCardToCanvasX.value = u),
          (e.uCardToCanvasY.value = h),
          (e.uSpotlightHover.value = eo));
    },
    eb = () => {
      let e = 0.1 * er,
        t = 0.06 * ei,
        r = Math.cos(t);
      (d.position.set(
        -Math.cos(e) * r * en,
        Math.sin(t) * en + 0.035 * ei * 0.7,
        -Math.sin(e) * r * en + 0.035 * er,
      ),
        d.lookAt(0, 0, 0));
    },
    ew = () => {
      let r = Math.max(1, e.clientWidth),
        i = Math.max(1, e.clientHeight),
        a = e.closest('[role="dialog"]'),
        s =
          "library" !== X && a?.clientWidth
            ? a.getBoundingClientRect().width / a.clientWidth
            : 1,
        u = Math.min(window.devicePixelRatio || 1, n ? 1 : 1.5) * s;
      ((r !== eu || i !== ed || Math.abs(u - eh) > 0.001) &&
        ((eu = r),
        (ed = i),
        (eh = u),
        o.setPixelRatio(u),
        o.setSize(r, i, !1),
        j.setPixelRatio(u),
        j.setSize(r, i),
        n && q.setSize(Math.ceil((r * u) / 2), Math.ceil((i * u) / 2))),
        (d.aspect = r / i));
      let h = l.getSize(new t.Vector3()),
        c = Math.max(
          1,
          e.closest("[data-character-model-frame]")?.clientHeight ?? i,
        );
      ((en = (function (e, r, i, o, a = 1.13) {
        let s = Math.tan(t.MathUtils.degToRad(0.5 * o));
        return (
          Math.max((0.5 * e.y) / s, (0.5 * e.z) / Math.max(s * r, 0.001)) *
          a *
          Math.max(i, 0.001)
        );
      })(h, d.aspect, i / c, d.fov)),
        (d.near = Math.max(0.01, en / 100)),
        (d.far = 10 * en),
        d.updateProjectionMatrix(),
        eb(),
        ep());
    };
  function eC() {
    Z || document.hidden || J || (J = window.requestAnimationFrame(ey));
  }
  let eS = new ResizeObserver(() => {
    (ew(), eC());
  });
  function ey(e) {
    if (((J = 0), Z || document.hidden)) return;
    let t = $ ? Math.min(0.05, (e - $) / 1e3) : 0;
    (($ = e),
      "loading" !== X || r || (ee += t * T(c).speed),
      (er += (ea - er) * 0.14),
      (ei += (es - ei) * 0.14),
      (eo += (el - eo) * 0.14));
    let i =
      0.002 > Math.abs(ea - er) &&
      0.002 > Math.abs(es - ei) &&
      0.002 > Math.abs(el - eo);
    if (
      (i && ((er = ea), (ei = es), (eo = el)),
      eb(),
      ep(),
      et && "loading" === X)
    ) {
      let t = Math.min(1, (e - et) / 500);
      (eg(t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2),
        t >= 1 && ((et = 0), ev()));
    } else "loading" === X && ev();
    (j.render(t), (!et && ("loading" !== X || r) && i) || eC());
  }
  (eS.observe(e), ew());
  let ex = () => {
    if (document.hidden) {
      (J && window.cancelAnimationFrame(J), (J = 0), ($ = 0));
      return;
    }
    eC();
  };
  return (
    document.addEventListener("visibilitychange", ex),
    ep(),
    eb(),
    j.render(),
    {
      setPhase: (e) => {
        ((X = e),
          "loading" === e
            ? ((H.material = z),
              (ee = 0),
              r ? ((et = 0), ev()) : ((et = performance.now()), eg(0)))
            : "result" === e
              ? ((et = 0), (H.material = z), ev())
              : ((et = 0), (H.material = W), ef(), em(0)),
          ew(),
          ($ = 0),
          eC());
      },
      setTheme: (e) => {
        if (c !== e) {
          let t, r, i;
          if (
            ((c = e),
            (t = ec()),
            (r = T(c)),
            S.set(t.surfaceColor),
            k.set(r.surfaceColor),
            L.set(t.color),
            D.set(r.color),
            A.set(r.rimColor),
            (i = R(c)),
            (I.uInk.value = i),
            (V.uInk.value = i),
            ef(),
            et && "loading" === X)
          ) {
            let e = Math.min(1, (performance.now() - et) / 500);
            eg(e < 0.5 ? 2 * e * e : 1 - (-2 * e + 2) ** 2 / 2);
          } else "loading" === X || "result" === X ? ev() : em(0);
        }
        eC();
      },
      setPointer: (e, i, o) => {
        (r || "result" === X || "edit" === X
          ? ((ea = 0), (es = 0), (el = 0))
          : ((ea = 0.04 > Math.abs(e) ? 0 : t.MathUtils.clamp(e, -1, 1)),
            (es = 0.04 > Math.abs(i) ? 0 : t.MathUtils.clamp(i, -1, 1)),
            (el = +!!o)),
          eC());
      },
      dispose: () => {
        Z ||
          ((Z = !0),
          J && window.cancelAnimationFrame(J),
          document.removeEventListener("visibilitychange", ex),
          eS.disconnect(),
          u.remove(H),
          s.dispose(),
          W.dispose(),
          z.dispose(),
          q.dispose(),
          K.dispose(),
          j.dispose(),
          (0, b.f)(o));
      },
    }
  );
}

export { N as createCharacterGenerationRenderer };
