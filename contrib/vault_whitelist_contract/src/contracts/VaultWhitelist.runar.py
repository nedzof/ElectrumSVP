from runar import (
    SmartContract, PubKey, Sig, Addr, SigHashPreimage, Bigint,
    public, assert_, check_sig, check_preimage, extract_output_hash, extract_amount,
    hash256, num2bin, cat,
)


class VaultWhitelist(SmartContract):
    owner: PubKey
    whitelist: Addr
    max_fee: Bigint

    def __init__(self, owner: PubKey, whitelist: Addr, max_fee: Bigint):
        super().__init__(owner, whitelist, max_fee)
        self.owner = owner
        self.whitelist = whitelist
        self.max_fee = max_fee

    @public
    def spend(self, payout_amount: Bigint, tx_preimage: SigHashPreimage, sig: Sig):
        assert_(check_sig(sig, self.owner))
        assert_(check_preimage(tx_preimage))
        assert_(payout_amount > 0)

        input_amount = extract_amount(tx_preimage)
        assert_(payout_amount <= input_amount)
        assert_(input_amount - payout_amount <= self.max_fee)

        p2pkh_script = cat(cat('1976a914', self.whitelist), '88ac')
        expected_output = cat(num2bin(payout_amount, 8), p2pkh_script)
        assert_(hash256(expected_output) == extract_output_hash(tx_preimage))
