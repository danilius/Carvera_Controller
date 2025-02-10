# Pre-requisites:
# - Working XCode installation to build iOS app
# - Homebrew installed
# - Python 3 installed
# - git installed

# Make sure it's the case
if ! command -v brew &> /dev/null
then
    echo "brew command could not be found"
    echo "Please install Homebrew from https://brew.sh/"
    exit
fi

if ! command -v python3 &> /dev/null
then
    echo "python3 command could not be found"
    echo "Please install Python 3 from https://www.python.org/downloads/"
    exit
fi

if ! command -v git &> /dev/null
then
    echo "git command could not be found"
    echo "Please install git from https://git-scm.com/downloads"
    exit
fi

if ! command -v xcode-select &> /dev/null
then
    echo "xcode-select command could not be found"
    echo "Please install XCode from the App Store"
    exit
fi

# Make sure we are in the top directory of the git repo
TOP_LEVEL=$(git rev-parse --show-toplevel)
cd $TOP_LEVEL || exit 1

# Make sure we have the right tools
# Install required tools if not already installed
for tool in autoconf automake libtool pkg-config; do
    if ! brew list -1 | grep -q "^${tool}\$"; then
        brew install ${tool}
    fi
done

# Create python venv if not there
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip3 install Cython


# Clone kivy-ios if not there
if [ ! -d "build/kivy-ios" ]; then
    git clone https://github.com/kivy/kivy-ios.git build/kivy-ios
fi

# Install dependencies
cd build/kivy-ios
pip install -e .
cd $TOP_LEVEL

# Build the kivy-ios toolchain and needed dpendencies
python3 build/kivy-ios/toolchain.py build --add-custom-recipe packaging_assets/ios/recipes/quicklz --add-custom-recipe packaging_assets/ios/recipes/pyserial kivy quicklz pyserial

