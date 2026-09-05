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
- Google, Android Auto, Google Automotive Link, and Desktop Head Unit are
  trademarks or software of their respective owners. This project is
  independent and does not redistribute Google's proprietary binaries or APKs.
- The expired CarService identity in `aa-linux/certs/dev/` is a publicly known
  development credential included solely for local DHU testing with the supplied
  time shim. It is not a production credential and must not be used with a car.
