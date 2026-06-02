\version "2.24.0"

\header { title = "Scale Test" }

\paper {
  system-count = 1
  paper-width = 9999\mm
  line-width = 9989\mm
  paper-height = 250\mm
  top-margin = 5\mm
  bottom-margin = 5\mm
  indent = 0
}

\score {
  \new Staff {
    \tempo 4 = 120
    \time 4/4
    c' d' e' f' | g' a' b' c'' | c'' b' a' g' | f' e' d' c'
  }
  \midi {}
  \layout {}
}
