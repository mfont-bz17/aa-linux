(() => {
  "use strict";

  const doc = document;

  /* Sidebar section highlighting */
  const sectionLinks = Array.from(doc.querySelectorAll(".side-nav a"));
  const sections = sectionLinks
    .map((link) => doc.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  if (sections.length) {
    let scheduled = false;

    const updateActiveSection = () => {
      const marker = window.scrollY + 90;
      let active = sections[0];

      sections.forEach((section) => {
        if (section.getBoundingClientRect().top + window.scrollY <= marker) {
          active = section;
        }
      });

      sectionLinks.forEach((link) => {
        link.classList.toggle("is-active", link.getAttribute("href") === `#${active.id}`);
      });

      scheduled = false;
    };

    const requestUpdate = () => {
      if (scheduled) return;
      scheduled = true;
      window.requestAnimationFrame(updateActiveSection);
    };

    updateActiveSection();
    window.addEventListener("scroll", requestUpdate, { passive: true });
    window.addEventListener("resize", requestUpdate);
  }

  /* Close the mobile contents panel after following a link */
  doc.querySelectorAll(".mobile-toc a").forEach((link) => {
    link.addEventListener("click", () => {
      const details = link.closest("details");
      if (details) details.open = false;
    });
  });

  /* Quick-start tabs */
  const tabs = Array.from(doc.querySelectorAll(".tab"));
  const panels = Array.from(doc.querySelectorAll(".tabpanel"));

  function activateTab(tab, moveFocus) {
    tabs.forEach((item) => {
      const selected = item === tab;
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected ? 0 : -1;
      if (selected && moveFocus) item.focus();
    });

    panels.forEach((panel) => {
      panel.hidden = panel.id !== `panel-${tab.dataset.tab}`;
    });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateTab(tab, false));

    tab.addEventListener("keydown", (event) => {
      let target = null;

      if (event.key === "ArrowRight") {
        target = tabs[(index + 1) % tabs.length];
      } else if (event.key === "ArrowLeft") {
        target = tabs[(index - 1 + tabs.length) % tabs.length];
      } else if (event.key === "Home") {
        target = tabs[0];
      } else if (event.key === "End") {
        target = tabs[tabs.length - 1];
      }

      if (target) {
        event.preventDefault();
        activateTab(target, true);
      }
    });
  });

  const selectedTab = tabs.find((tab) => tab.getAttribute("aria-selected") === "true");
  if (selectedTab) activateTab(selectedTab, false);

  /* Copy the active terminal example */
  const copyButton = doc.querySelector("[data-copy]");
  if (copyButton) {
    const copyLabel = copyButton.querySelector("span");

    copyButton.addEventListener("click", async () => {
      const activePanel = panels.find((panel) => !panel.hidden);
      const code = activePanel && activePanel.querySelector("code");
      if (!code) return;

      const text = code.innerText.replace(/\u00a0/g, " ").trim();
      let copied = false;

      try {
        await navigator.clipboard.writeText(text);
        copied = true;
      } catch (error) {
        const helper = doc.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        doc.body.appendChild(helper);
        helper.select();
        try {
          copied = doc.execCommand("copy");
        } catch (fallbackError) {
          copied = false;
        }
        helper.remove();
      }

      if (!copied) return;

      const previousLabel = copyLabel.textContent;
      copyButton.classList.add("is-copied");
      copyLabel.textContent = "Copied";

      window.clearTimeout(copyButton._copyTimer);
      copyButton._copyTimer = window.setTimeout(() => {
        copyButton.classList.remove("is-copied");
        copyLabel.textContent = previousLabel;
      }, 1600);
    });
  }

  /* Screenshot lightbox */
  const shots = Array.from(doc.querySelectorAll("[data-lightbox]"));
  const dialog = doc.getElementById("lightbox");

  if (dialog && shots.length) {
    const image = doc.getElementById("lightbox-img");
    const counter = doc.getElementById("lightbox-count");
    const caption = doc.getElementById("lightbox-caption");
    const openLink = doc.getElementById("lightbox-open");
    const previousButton = doc.getElementById("lightbox-prev");
    const nextButton = doc.getElementById("lightbox-next");
    const closeButton = doc.getElementById("lightbox-close");

    let currentIndex = 0;

    const showShot = (index) => {
      currentIndex = (index + shots.length) % shots.length;

      const shot = shots[currentIndex];
      const thumbnail = shot.querySelector("img");

      image.src = shot.getAttribute("href");
      image.alt = thumbnail ? thumbnail.alt : "";
      caption.textContent = shot.dataset.caption || shot.getAttribute("href");
      counter.textContent = `${currentIndex + 1} / ${shots.length}`;
      openLink.href = shot.getAttribute("href");
    };

    const openLightbox = (index) => {
      showShot(index);
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      doc.body.classList.add("no-scroll");
    };

    const closeLightbox = () => {
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
      doc.body.classList.remove("no-scroll");
    };

    shots.forEach((shot, index) => {
      shot.addEventListener("click", (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        openLightbox(index);
      });
    });

    previousButton.addEventListener("click", () => showShot(currentIndex - 1));
    nextButton.addEventListener("click", () => showShot(currentIndex + 1));
    closeButton.addEventListener("click", closeLightbox);

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeLightbox();
    });

    dialog.addEventListener("close", () => {
      doc.body.classList.remove("no-scroll");
    });

    dialog.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        showShot(currentIndex - 1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        showShot(currentIndex + 1);
      }
    });
  }
})();
