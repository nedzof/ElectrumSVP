
Beta Release Notice
==================

This is a beta release of ElectrumSVP (v0.0.1-beta). Use with caution.  
Do not store large amounts of BSV in this version.

Read more about the beta release here:  https://crypto-rebel.medium.com/electrum-svp-beta-release-desktop-bitcoin-wallet-401030f93443


Beta Warning: This is a pre-release beta version of the wallet. It may contain bugs, incomplete 
features, or other issues. Using this wallet could result in loss of coins or other unexpected 
behavior. Use at your own risk and do not store significant funds here. 

Welcome to the Beta release of our custom ElectrumSV wallet build. This version is intended for 
testing and feedback before the official release. We encourage users to explore the new features 
and report any bugs or issues encountered. 
For a full overview of changes and development notes, please visit our beta release article. 

Dependencies: Upgraded major dependencies, including Bitcoinx 0.9.0. Code was refactored to 
accommodate API changes and new features in the latest libraries. 

BEEF SPV verification: Added SPV proof functions for transactions/UTXOs and addresses, enhancing 
on-chain and off-chain verification. 

BIP39 seeds: BIP39 seed support has been added as the default for wallet creation. 

Sweep function: Added a new sweep function to import private keys. Supports BIP38 decryption, 
compressed and uncompressed keys, BEEF UTXO import. 

Destinations tab: The previous "Keys" tab has been revamped and renamed "Destinations", now 
displaying addresses along with their derivation paths. 

Coin control: Added freeze/unfreeze controls for addresses in the address tab. Fixed a bug where 
frozen coins persisted incorrectly between sessions. 

Block headers: Introduced a new Block Headers file format compatible with Bitcoinx 0.9.0, 
including meta data. The headers file is synced to a recent tip and preloaded for faster startup. 

Hardware wallets: Bundled hardware wallet dependencies. Feature is present but not fully 
functional in this beta. 

User interface: 

Coinsplit tab hidden by default. 

Other tabs reorganized with improved UI layout. 

New units available: "Bitcoin", "BSV", "BSV blockchain tokens", "millibitcoin". 

Explorers & Servers: Updated block explorers and removed outdated ones. Default server list 
updated for reliability. 

AppImage improvements: Improved Linux compatibility. No longer requires libfuse2 on some systems, 
maintaining full compatibility with TAILS. 

Testing notes: As this is a beta release, please be cautious with hardware wallets, and report any 
issues encountered during usage. Your feedback is valuable for the upcoming official release. 

Thank you for testing this beta release and helping us improve the wallet! 


TruthMachine PGP public key:

-----BEGIN PGP PUBLIC KEY BLOCK-----

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
E8apWk0u
=qwPR
-----END PGP PUBLIC KEY BLOCK-----

Fingerprint:  E9BA FA19 B15E 6C2C 158C  DD40 0DB1 6C74 A9CA 7CF6










|azureboards_badge| |crowdin_badge| |azurepipeline_badge|

.. |azureboards_badge| image:: https://dev.azure.com/electrumsv/dc4594d0-46c9-4b75-ad35-f7fb21ce6933/46962181-6adc-4d37-bf1a-4f3f98c9c649/_apis/work/boardbadge/74437d75-4be7-4c91-8049-518350865962
    :target: https://dev.azure.com/electrumsv/dc4594d0-46c9-4b75-ad35-f7fb21ce6933/_boards/board/t/46962181-6adc-4d37-bf1a-4f3f98c9c649/Microsoft.RequirementCategory
    :alt: Board Status \
.. |azurepipeline_badge| image:: https://dev.azure.com/electrumsv/ElectrumSV/_apis/build/status/electrumsv.electrumsv?branchName=master
    :target: https://dev.azure.com/electrumsv/ElectrumSV/_build/latest?definitionId=4&branchName=master
    :alt: Build status on Azure Pipelines \
.. |crowdin_badge| image:: https://d322cqt584bo4o.cloudfront.net/electrumsv/localized.svg
    :target: https://crowdin.com/project/electrumsv
    :alt: Help translate ElectrumSV online

ElectrumSV - Lightweight Bitcoin SV client
==========================================

::

  Licence: Open BSV
  Maintainers: Neil Booth, Roger Taylor, AustEcon
  Project Lead: Roger Taylor
  Language: Python (requires Python 3.9 later than 3.9.13. 3.10 and 3.11 not officially supported)
  Homepage: https://electrumsv.io/

Getting started on Linux/MacOS
==============================

ElectrumSV is a Python-based application forked from Electrum Core.

If you are running from the Github repository, you are advised to use the latest release branch,
which at this time is `releases/1.3`. The `develop` branch is used for the latest development
changes and is not guaranteed to be as stable, or to have guaranteed long term support for some of
the more advanced features we may have added and later remove. The `master` branch is frozen, out
of date and will be overwritten by `develop` evenutally.

Ensuring you have at least Python 3.9.13
----------------------------------------

The ElectrumSV builds are created using Python 3.9.13 because these are the last release for
Python 3.9 that the Python development team do binary releases for. This is the minimum allowed
version of Python to use, we explicitly rule out running against earlier versions and we cannot
guarantee later versions like 3.10 and 3.11 will work reliably due to breaking changes by the
Python language developers.

You need to ensure you have Python 3.9.13 or later, the following command should look like this::

    $ python3 --version
    Python 3.9.16

You can use pyenv to install Python 3.9.16. First install pyenv::

    curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash

Edit your .bashrc file as described, and then ensure the changes are put into effect::

    $ source ~/.profile

Now you can install Python 3.9.16 using pyenv::

    $ pyenv install 3.9.16

If you encounter errors during that process, you can refer to the
`pyenv common problems <https://github.com/pyenv/pyenv/wiki/common-build-problems>`_.

At this point, you can make Python 3.9.16 the default Python on your computer::

    $ pyenv global 3.9.16

And you can check that your `python3` version is indeed 3.9.16, by confirming the following command
now looks like this::

    $ python3 --version
    Python 3.9.16

Ensuring you have at least Sqlite 3.31.1
----------------------------------------

ElectrumSV MacOS and Windows builds come with at least Sqlite version 3.31.1, but there are no
Linux builds, and both Linux and MacOS users may wish to upgrade or make available the Sqlite
version on their computer.

MacOS::

    $ brew upgrade sqlite3
    $ python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
    3.31.1

Linux::

    $ python3 -m pip install -U pysqlite3-binary
    $ python3 -c "import pysqlite3; print(pysqlite3.sqlite_version)"
    3.31.1

You may see a different version displayed than 3.31.1, but as long as it is higher, this is fine.

Installing other dependencies
-----------------------------

If you are running ElectrumSV from source, first install the dependencies::

MacOS::

    brew install pyqt5
    pip3 install --user -r contrib/deterministic-build/macos-py3.9-requirements-electrumsv.txt

Linux::

    sudo apt-get install python3-pyqt5
    pip3 install --user -r contrib/deterministic-build/linux-py3.9-requirements-electrumsv.txt

Your should now be able to run ElectrumSV::

MacOS::

    python3 electrum-sv

Linux::

    python3 electrum-sv

You can also install ElectrumSV on your system. In order to do so, run the following command::

    pip3 install . --no-dependencies

Problem Solving
---------------

If you choose to use Linux, you introduce complexity and uncertainty into the process. It is not
possible to know all the unique choices you have made regarding it. The following tips may help
work around problems you encounter.

Errors relating to "wheels"
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you encounter problems referring to wheels, make sure you have installed the wheel package::

    pip3 install --user wheel

Errors relating to "libusb" installing the pip3 requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install the following::

    sudo apt install libusb-1.0.0-dev libudev-dev

Errors relating to "Python.h"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you encounter problems referring to "Python.h", first check your Python version::

    python3 --version

If it says "3.9", then install the following::

    sudo apt install python3.9-dev

If it says a later version of Python, you should be able to figure out what to do.

Scanning QR codes
~~~~~~~~~~~~~~~~~

If you need to enable QR code scanning functionality, install the following::

    sudo apt-get install zbar-tools

Getting started on Windows
==========================

The easiest way to run ElectrumSV on Windows, is to obtain an executable for the latest version
from our website. This Git repository has a `build-hashes.txt` which should contain SHA-256
hashes for all our downloads. You can confirm that you have downloaded a valid file, by comparing
it's SHA-256 hash to the hash we provide for the same file name.

You can also run from the Git repository directly, which is useful if you wish to customise
or help us develop ElectrumSV.

You need to be sure that you are using a version of Python either 3.9.13 or higher. And that the
version you are using has a version of Sqlite either 3.31.1 or higher. If you are for instance
using a version of Python 3.8 that has a lower version of Sqlite, then update your Python 3.8
installation.

To run ElectrumSV from its top-level directory, first install the core dependencies::

    py -3.9 -m pip install --user -r contrib/deterministic-build/win64-py3.9-requirements-electrumsv.txt

Then invoke it as so::

    py -3.9 electrum-sv

You can also install ElectrumSV on your system. This will download and install most dependencies
used by ElectrumSV. This is useful if you with to use the `electrumsv` Python library, perhaps
for Bitcoin application development using ElectrumSV as a wallet server.

In order to do so, run these commands::

    pip3 install . --no-dependencies

Extra development notes
=======================

Check out the code from Github::

    git clone https://github.com/ElectrumSV/ElectrumSV
    cd ElectrumSV

Run the pip installs (this should install dependencies)::

    pip3 install .

Create translations (optional)::

    sudo apt-get install python-requests gettext
    ./contrib/make_locale

Running unit tests (with the `pytest` package)::

    pytest electrumsv/tests

Running pylint::

    pylint --rcfile=.pylintrc electrum-sv electrumsv

Running mypy::

    mypy --config-file mypy.ini --python-version 3.9


Builds
======

Builds are created automatically for Git commits through the Azure Pipelines CI services which
Microsoft and Github kindly make available to us.

The easiest way for you to create builds is to fork the project, and to link it to Azure Pipelines
and they should also happen automatically.  If you wish to look at the specific code that
handles a given part of the build process, these will be referenced below for the various
operating systems.  To see how these are engaged, refer to the Azure Pipelines YAML files.

Source Archives
---------------

Run the following to create the release archives under `dist/`::

    ./contrib/make_source_archives.py

Mac OS X / macOS
----------------

See `contrib/osx/`.


Windows
-------

See `contrib/build-wine/`.
