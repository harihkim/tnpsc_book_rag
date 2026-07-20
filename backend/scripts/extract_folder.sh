#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/extract_folder.sh INPUT_DIR OUTPUT_DIR STANDARD TERM [options]

Extract every PDF directly inside INPUT_DIR as a verified 256-token package-v2 archive.
The subject is inferred from each filename: English, Mathematics/Maths, Science, or Social Science.

Options:
  --device auto|cuda|cpu  Docling accelerator (default: auto)
  --rechunk-384           Also create a 384-token variant without rerunning Docling
  -h, --help              Show this help

Environment:
  PYTHON_BIN              Python executable (default: python)
  HF_TOKEN                Optional Hugging Face token for higher download rate limits
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi
if (( $# < 4 )); then
  usage >&2
  exit 2
fi

input_dir=$1
output_dir=$2
standard=$3
term=$4
shift 4

device=auto
rechunk_384=false
while (( $# > 0 )); do
  case $1 in
    --device)
      if (( $# < 2 )); then
        printf '%s\n' "--device requires auto, cuda, or cpu" >&2
        exit 2
      fi
      device=$2
      shift 2
      ;;
    --rechunk-384)
      rechunk_384=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d $input_dir ]]; then
  printf 'input directory does not exist: %s\n' "$input_dir" >&2
  exit 2
fi
if [[ ! $standard =~ ^(6|7|8|9|10)$ ]]; then
  printf 'STANDARD must be between 6 and 10\n' >&2
  exit 2
fi
if [[ ! $term =~ ^(1|2|3)$ ]]; then
  printf 'TERM must be 1, 2, or 3\n' >&2
  exit 2
fi
if [[ ! $device =~ ^(auto|cuda|cpu)$ ]]; then
  printf '%s\n' "--device must be auto, cuda, or cpu" >&2
  exit 2
fi

case $term in
  1) edition="Term I" ;;
  2) edition="Term II" ;;
  3) edition="Term III" ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python_bin=${PYTHON_BIN:-python}
if [[ $python_bin == */* ]]; then
  if [[ ! -x $python_bin ]]; then
    printf 'PYTHON_BIN is not executable: %s\n' "$python_bin" >&2
    exit 2
  fi
elif ! command -v "$python_bin" >/dev/null 2>&1; then
  printf 'Python executable is unavailable: %s\n' "$python_bin" >&2
  exit 2
fi

infer_subject() {
  local filename=${1,,}
  case $filename in
    *social*science*) printf '%s' "Social Science" ;;
    *mathematics*|*maths*|*math*) printf '%s' "Mathematics" ;;
    *science*) printf '%s' "Science" ;;
    *english*) printf '%s' "English" ;;
    *) return 1 ;;
  esac
}

slugify() {
  local value=${1,,}
  value=${value//[^a-z0-9]/-}
  while [[ $value == *--* ]]; do
    value=${value//--/-}
  done
  value=${value#-}
  value=${value%-}
  printf '%s' "$value"
}

mkdir -p -- "$output_dir"
mapfile -d '' pdfs < <(find "$input_dir" -maxdepth 1 -type f -iname '*.pdf' -print0 | sort -z)
if (( ${#pdfs[@]} == 0 )); then
  printf 'no PDF files found directly inside: %s\n' "$input_dir" >&2
  exit 2
fi

for pdf in "${pdfs[@]}"; do
  filename=$(basename -- "$pdf")
  stem=${filename%.*}
  if ! subject=$(infer_subject "$filename"); then
    printf 'cannot infer subject from filename: %s\n' "$filename" >&2
    exit 2
  fi
  slug=$(slugify "$stem")
  title="Tamil Nadu State Board Standard ${standard} ${subject}"
  output_256="$output_dir/${slug}-256"
  archive_256="$output_dir/${slug}-256.zip"

  if [[ -d $output_256 && -f $archive_256 ]]; then
    printf 'skip complete 256-token package: %s\n' "$filename"
  elif [[ -e $output_256 || -e $archive_256 ]]; then
    printf 'partial output exists for %s; move or remove it before retrying\n' "$filename" >&2
    exit 1
  else
    "$python_bin" "$script_dir/extract_book.py" \
      "$pdf" \
      "$output_256" \
      --title "$title" \
      --standard "$standard" \
      --subject "$subject" \
      --term "$term" \
      --publisher "Government of Tamil Nadu" \
      --edition "$edition" \
      --device "$device" \
      --child-max-tokens 256 \
      --parent-soft-tokens 800 \
      --parent-hard-tokens 1200 \
      --archive "$archive_256"
  fi

  if [[ $rechunk_384 == true ]]; then
    output_384="$output_dir/${slug}-384"
    archive_384="$output_dir/${slug}-384.zip"
    if [[ -d $output_384 && -f $archive_384 ]]; then
      printf 'skip complete 384-token package: %s\n' "$filename"
    elif [[ -e $output_384 || -e $archive_384 ]]; then
      printf 'partial 384-token output exists for %s; move or remove it before retrying\n' \
        "$filename" >&2
      exit 1
    else
      "$python_bin" "$script_dir/rechunk_book.py" \
        "$archive_256" \
        "$output_384" \
        --child-max-tokens 384 \
        --archive "$archive_384"
    fi
  fi
done

printf 'completed %d PDF file(s) from %s\n' "${#pdfs[@]}" "$input_dir"
