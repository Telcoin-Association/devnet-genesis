status: done
unit: RS (devnet-release-sign.sh in dg-l2)
updated: 2026-11-17T20:34:42Z
completed sections:
- RS code written (dg-l2/devnet-release-sign.sh, 581 lines); gates bash -n / shellcheck -x / portability rc 0
- scratch RS/ suite R1-R18 with throwaway gpg key (scratch GNUPGHOME + scratch keys dir): unset path byte-identical to HEAD (SHA256SUMS, IMAGE_DIGEST, prepare+verify stdout); gw prepare/pending(3)/signed verify(0); mismatch/edited/placeholder/bad/unset cases rc1; old manifest + GATEWAY set -> rc1 gateway-missing msg (signed) / rc3 (unsigned); --force path to rc0
- consumer grep: no DG driver ships the manifest; finalize runs verify locally
