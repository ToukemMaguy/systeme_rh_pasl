// Configuration Tailwind de PASL-RH (couleurs, arrondis, police), autrefois écrite dans chaque page.
// Pour régénérer app/static/vendor/tailwind.css après avoir modifié des pages : voir construire_css.bat
module.exports = Object.assign({
  // Fichiers où Tailwind cherche les classes utilisées
  content: ["../app/templates/**/*.html", "../app/**/*.py", "../app/static/**/*.js"],
}, {
      theme: {
        extend: {
          colors: {
            "outline-variant": "#c0c7cf", "surface-dim": "#d3daea", "on-tertiary": "#ffffff",
            "surface-container-low": "#f0f3ff", "on-primary-fixed": "#001e2f", "surface": "#f9f9ff",
            "surface-variant": "#dce2f3", "error-container": "#ffdad6", "primary-fixed-dim": "#93cdf9",
            "tertiary-fixed-dim": "#9fcaff", "background": "#f9f9ff", "on-tertiary-container": "#95c4ff",
            "on-surface": "#151c27", "on-primary": "#ffffff", "inverse-on-surface": "#ebf1ff",
            "surface-container-highest": "#dce2f3", "inverse-primary": "#93cdf9", "surface-container-lowest": "#ffffff",
            "primary-fixed": "#c9e6ff", "on-secondary-container": "#15637f", "surface-bright": "#f9f9ff",
            "on-primary-fixed-variant": "#004b6f", "secondary-container": "#9cddfe", "secondary-fixed": "#bfe8ff",
            "error": "#ba1a1a", "tertiary-container": "#00518c", "on-tertiary-fixed": "#001d37",
            "tertiary": "#003a66", "outline": "#71787f", "secondary": "#1a6682",
            "surface-container": "#e7eefe", "on-tertiary-fixed-variant": "#00497e", "on-secondary": "#ffffff",
            "on-primary-container": "#8ec7f3", "on-background": "#151c27", "primary": "#003c59",
            "on-secondary-fixed-variant": "#004d65", "on-error-container": "#93000a", "primary-container": "#06547a",
            "surface-tint": "#23648a", "on-error": "#ffffff", "inverse-surface": "#2a313d",
            "tertiary-fixed": "#d2e4ff", "on-secondary-fixed": "#001f2a", "on-surface-variant": "#41484e",
            "secondary-fixed-dim": "#8ecfef", "surface-container-high": "#e2e8f8"
          },
          borderRadius: { DEFAULT: "0.25rem", lg: "0.5rem", xl: "0.75rem", full: "9999px" },
          spacing: { "space-sm": "0.5rem", margin: "1.5rem", "space-lg": "1.5rem", "space-xl": "2rem", gutter: "1.5rem", "space-xs": "0.25rem", "space-md": "1rem" },
          fontFamily: { sans: ["Inter", "sans-serif"] }
        }
      }
    });
