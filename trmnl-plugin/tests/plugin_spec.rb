# frozen_string_literal: true

require_relative 'spec_helper'

# This plugin's tests, run with `make plugin-test` (trmnlp test; add `--report report` for a page of every
# screen it drew). Docs: https://github.com/usetrmnl/trmnlp#testing-plugins
RSpec.describe 'Patent of the Moment' do
  include PatentFixtures

  let(:now) { '2026-12-01T12:00:00Z' }
  let(:data) { PatentFixtures.mini(6) }
  let(:mocks) { {} }
  let(:custom_fields) { {} }

  # Every view on TRMNL's devices, a failing API, and dark mode, checked for page errors and leaked values.
  it_behaves_like 'a publishable recipe'

  describe 'the transform' do
    # Runs the transform `times` times, feeding each run's saved state to the next; returns every run.
    def refreshes(times, data:, state: {}, now: '2026-12-01T12:00:00Z')
      Array.new(times) do
        trmnl.transform(data:, state:, now:).tap { state = it.state }
      end
    end

    it 'shows every patent once before any repeats, across reshuffles too' do
      runs = refreshes(18, data: PatentFixtures.mini(6))
      ids = runs.map { it.data['id'] }
      expect(ids.each_slice(6).map(&:uniq).map(&:size)).to all(eq 6)
      expect(ids.each_cons(2).count { |a, b| a == b }).to eq 0
    end

    it 'changes its merge variables on every refresh, even with one patent' do
      runs = refreshes(3, data: PatentFixtures.mini(1))
      expect(runs.map { it.data['id'] }.uniq.size).to eq 1
      expect(runs.map { it.data['pick_id'] }).to eq [1, 2, 3]
    end

    it 'does not treat the back catalogue as new on the first run' do
      run = trmnl.transform(data: PatentFixtures.mini(6, added: '2026-11-30T00:00:00Z'), state: {}, now:)
      expect(run.data['is_new']).to be false
      expect(run.state['seen']).to eq now
    end

    it 'shows a newly added patent first, once, then resumes the queue' do
      state = refreshes(2, data: PatentFixtures.mini(5)).last.state
      added = PatentFixtures.patents[5].merge('added' => '2026-12-01T13:00:00Z')
      data = PatentFixtures.mini(5).tap { it['patents'] << added }
      runs = refreshes(4, data:, state:, now: '2026-12-01T13:30:00Z')
      expect(runs.first.data).to include('id' => added['id'], 'is_new' => true)
      expect(runs.drop(1).map { it.data['id'] }).not_to include(added['id'])
      expect(runs.drop(1).map { it.data['is_new'] }).to all(be false)
    end

    it 'stays within TRMNL limits: small output, small state, quick' do
      run = trmnl.transform(data: PatentFixtures.manifest, state: {}, now:)
      expect(JSON.generate(run.data).bytesize).to be < 5 * 1024
      expect(JSON.generate(run.state).bytesize).to be < 8 * 1024
      expect(run.duration_ms).to be < 1000
      expect(run.error).to be_nil
    end
  end

  # Every patent in every view, on the original TRMNL in 4-gray mode. Writes each screen to
  # $CONTACT_DIR/<view>/<slug>.png (plus the slot's box) for the contact sheets, when set.
  describe 'every patent' do
    PatentFixtures.patents.select { ENV['ONLY'].nil? || it['slug'].include?(ENV['ONLY']) }.each do |patent|
      PatentFixtures::VIEWS.each do |view|
        it "lays out #{patent['slug']} in #{view}" do
          screen = trmnl.render(view:, device: 'og_plus', data: PatentFixtures.manifest,
                                state: PatentFixtures.state_picking(patent['id']), now:)
          expect(screen).to have_no_problems
          expect(screen.overflowing).to be_empty

          lines = screen.evaluate(<<~JS)
            (() => {
              const lineCount = (el) => el ? Math.round(el.getBoundingClientRect().height /
                parseFloat(getComputedStyle(el).lineHeight)) : 0;
              const fits = (el) => [...el.children].every((s) => s.scrollWidth <= Math.ceil(el.parentElement.getBoundingClientRect().width) + 1);
              const caption = document.querySelector('.pw-caption').getBoundingClientRect();
              const canvas = document.querySelector('.pw').getBoundingClientRect();
              return {
                header: [...document.querySelectorAll('.pw-header > span')].map(lineCount),
                title: [...document.querySelectorAll('.pw-title > span')].map(lineCount),
                inventors: document.querySelector('.pw-inventors')?.textContent || '',
                inside: caption.left >= canvas.left - 1 && caption.right <= canvas.right + 1 &&
                        caption.top >= canvas.top - 1 && caption.bottom <= canvas.bottom + 1,
                titleFits: fits(document.querySelector('.pw-title')),
              };
            })()
          JS
          expect(lines['header']).to all(eq 1)
          expect(lines['title'].size).to be <= PatentFixtures::MAX_TITLE_LINES[view]
          expect(lines['title']).to all(eq 1)
          expect(lines['titleFits']).to be true
          expect(lines['inside']).to be true
          # The caption was painted onto its antialiased canvas (see shared.liquid).
          expect(screen.evaluate("document.querySelector('.pw-caption').classList.contains('pw-painted')")).to be true
          expect(lines['inventors']).not_to be_empty if patent['inventors'].to_s != ''

          if (dir = ENV['CONTACT_DIR'])
            FileUtils.mkdir_p(File.join(dir, view))
            base = File.join(dir, view, patent['slug'])
            FileUtils.cp(screen.png_path, "#{base}.png")
            File.write("#{base}.json", JSON.generate(screen.box('.view').to_h))
          end
        end
      end
    end
  end
end
