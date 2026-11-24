# frozen_string_literal: true

require 'json'
require 'fileutils'

# The manifest `make plugin` writes, read from the repo checkout (trmnlp runs from the repo root, see
# the Makefile). Drawings and fonts load from the same build through asset_overrides in .trmnlp.yml.
module PatentFixtures
  MANIFEST_PATH = File.expand_path('../../output/plugin/manifest.json', __dir__)
  VIEWS = %w[full half_horizontal half_vertical quadrant].freeze
  # Most title lines each view may use (src/plugin.py sets them; quadrant allows three).
  MAX_TITLE_LINES = { 'full' => 2, 'half_horizontal' => 2, 'half_vertical' => 2, 'quadrant' => 3 }.freeze

  module_function

  def manifest = @manifest ||= JSON.parse(File.read(MANIFEST_PATH))

  def patents = manifest['patents']

  # A small manifest for the transform tests: the first `n` patents, dated `added`.
  def mini(n, added: '2026-01-01T00:00:00Z')
    manifest.merge('patents' => patents.first(n).map { it.merge('added' => added) })
  end

  # Saved state that makes the transform pick `id` next (nothing counts as new).
  def state_picking(id) = { 'q' => [id], 'seen' => '9999-12-31T00:00:00Z', 'n' => 0 }
end
