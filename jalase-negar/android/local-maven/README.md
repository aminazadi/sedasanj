# local-maven

`ir.myket:billing:2.2-jn1` is the Myket billing SDK 2.2 with the `com.android.vending.billing.*`
(IInAppBillingService AIDL) classes removed from its `classes.jar`. `flutter_poolakey` (Bazaar)
ships the same AIDL interface (a superset: the same seven methods in the same order, plus three
more), and both SDKs in one app made `checkDuplicateClasses` fail. `android/build.gradle.kts`
substitutes `ir.myket:billing` with this copy. Everything else in the aar is unchanged.

Recreate: take `billing-2.2.aar` from Myket's repository, run
`zip -d classes.jar 'com/android/vending/billing/*'` inside the unpacked aar and re-zip it.
Not verified on a phone: the Myket purchase flow with the Poolakey copy of the interface.
