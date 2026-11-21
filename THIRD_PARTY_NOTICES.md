# Third-Party Notices

- The protobuf definitions include attribution to prior open Android Auto
  interoperability projects, including
  [`mrmees/open-android-auto`](https://github.com/mrmees/open-android-auto).
  Their individual notices and SPDX identifiers remain in `aa-linux/protos/`.
- Generated protobuf Python modules are derived from the checked-in `.proto`
  sources and the protobuf runtime is an external dependency.
- FFmpeg, X11, BlueZ, NetworkManager, Linux FunctionFS, and the Desktop Head
  Unit are external components. They are not bundled by this repository and
  retain their own licenses and terms.
- The bundled `openbox-desktop` layout is based on the
  [`justaguylinux/openbox-setup`](https://codeberg.org/justaguylinux/openbox-setup)
  project. Its original attribution and license terms remain with that project.
- The Tux mascot artwork used in the logo artwork under
  `docs/artwork/assets/logo-*` was created by
  Larry Ewing with The GIMP. Permission to use and/or
  modify the image is granted provided Larry Ewing and The GIMP are
  acknowledged. The logo compositions are part of the aa-linux project page.
- Google, Android Auto, Google Automotive Link, and Desktop Head Unit are
  trademarks or software of their respective owners. This project is
  independent and does not redistribute Google's proprietary binaries or APKs.
- The expired CarService identity in `aa-linux/certs/dev/` is a publicly known
  development credential included solely for local DHU testing with the supplied
  time shim. It is not a production credential and must not be used with a car.
